"""
# backend/move_engine.py
Selects a move that blends Stockfish's engine strength with the user's StyleProfile.

Algorithm (from CLAUDE.md):
  1. Ask Stockfish for top-N candidate moves
  2. Score each candidate against StyleProfile using weighted factors
  3. Softmax-sample from scored candidates
"""

from __future__ import annotations

import asyncio
import math
import random

import chess
import chess.engine

from models import StyleProfile, StyleScores

# Stockfish subprocess is expensive to start — keep one alive per process.
_engine: chess.engine.SimpleEngine | None = None
_engine_lock = asyncio.Lock()

# Opening phase ends at this fullmove number (half-moves = 2×)
OPENING_PHASE_MOVES = 15

# Piece values in centipawns (for sacrifice detection)
_PIECE_VALUE = {
    chess.PAWN: 100,
    chess.KNIGHT: 300,
    chess.BISHOP: 300,
    chess.ROOK: 500,
    chess.QUEEN: 900,
    chess.KING: 0,
}


def _skill_think_time(skill_level: int) -> float:
    """
    Think time scales with skill: weak players rush (0.15s), strong players
    take their time (0.6s). This gives Stockfish enough depth to meaningfully
    differentiate candidates at higher skill levels.
    """
    return 0.15 + (skill_level / 20) * 0.45


def _skill_top_n(skill_level: int) -> int:
    """
    Candidate pool shrinks as skill increases.
    A 2000 player realistically plays from 3–4 moves; a 1000 player from 6–8.
    Smaller pool + longer think = candidates are meaningfully ranked.
    """
    return max(3, 8 - round(skill_level / 4))


def _rating_to_skill_level(rating: int) -> int:
    """
    Map a Lichess rating to a Stockfish Skill Level (0–20).

    Approximate calibration:
      800  → 1   (beginner)
      1500 → 8   (club player)
      2000 → 14  (strong amateur)
      2500 → 19  (master)
      2800+→ 20  (maximum)
    """
    skill = round((rating - 800) / 100)
    return max(1, min(20, skill))


async def _get_engine(stockfish_path: str, skill_level: int = 20) -> chess.engine.SimpleEngine:
    """Return the shared Stockfish engine, starting it if needed."""
    global _engine
    async with _engine_lock:
        if _engine is None or _engine.returncode is not None:
            _engine = await asyncio.to_thread(
                chess.engine.SimpleEngine.popen_uci, stockfish_path
            )
        # Apply skill level every call — cheap UCI option set
        _engine.configure({"Skill Level": skill_level})
    return _engine


# ---------------------------------------------------------------------------
# Individual scoring components
# ---------------------------------------------------------------------------

def _score_opening_affinity(
    move: chess.Move,
    board: chess.Board,
    profile: StyleProfile,
    engine_score: float,
) -> float:
    """
    0–1: how well this move matches the player's opening repertoire.

    Move 1 as White: check against white_first_moves frequencies directly.
    Move 1 as Black: check against black_responses for the opponent's first move.
    Moves 2–OPENING_PHASE_MOVES: ECO family alignment heuristic.
    After opening phase: pure engine score.
    """
    move_number = board.fullmove_number
    to_move = board.turn

    if move_number == 1 and to_move == chess.WHITE:
        # White's first move — compare against recorded first-move preferences
        freq = profile.opening_dna.white_first_moves.get(move.uci(), 0.0)
        if profile.opening_dna.white_first_moves:
            # Scale: top move gets ~1.0, unlisted moves get 0.2 baseline
            max_freq = max(profile.opening_dna.white_first_moves.values())
            return 0.2 + 0.8 * (freq / max_freq) if max_freq > 0 else 0.5
        return 0.5

    if move_number == 1 and to_move == chess.BLACK:
        # Black's response — look up by White's first move
        if board.move_stack:
            white_first = board.peek().uci()
            responses = profile.opening_dna.black_responses.get(white_first, {})
            freq = responses.get(move.uci(), 0.0)
            if responses:
                max_freq = max(responses.values())
                return 0.2 + 0.8 * (freq / max_freq) if max_freq > 0 else 0.5
        return 0.5

    if move_number <= OPENING_PHASE_MOVES:
        # Mid-opening: ECO family alignment.
        # Determine player's preferred pawn center from their top ECO codes.
        top_ecos = list(profile.opening_dna.eco_frequency.keys())[:3]
        eco_letters = {e[0] for e in top_ecos if e}

        piece = board.piece_at(move.from_square)
        is_center_pawn = (
            piece is not None
            and piece.piece_type == chess.PAWN
            and move.to_square in (chess.E4, chess.E5, chess.D4, chess.D5)
        )
        is_flank = (
            piece is not None
            and piece.piece_type == chess.PAWN
            and move.to_square in (chess.C4, chess.C5, chess.F4, chess.F5,
                                    chess.B4, chess.B5, chess.G4, chess.G5)
        )

        eco_bonus = 0.0
        if "C" in eco_letters or "B" in eco_letters:  # e4 player
            eco_bonus = 0.15 if is_center_pawn else 0.0
        elif "D" in eco_letters or "E" in eco_letters:  # d4 player
            eco_bonus = 0.15 if is_center_pawn else 0.0
        elif "A" in eco_letters:  # flank player
            eco_bonus = 0.15 if is_flank else 0.0

        # Blend engine score (soundness) with ECO alignment
        return min(1.0, engine_score * 0.85 + eco_bonus)

    # Post-opening: pure engine score
    return engine_score


def _move_aggression(move: chess.Move, board: chess.Board) -> float:
    """
    Continuous aggression score for a single move (0–1).

    0.0  quiet development / king safety
    0.2  pawn advance (non-capturing)
    0.4  even exchange (equal piece values)
    0.6  pawn capture / minor piece capture
    0.7  check
    0.85 winning capture (takes higher-value piece)
    1.0  sacrifice (gives up higher-value piece)
    """
    piece = board.piece_at(move.from_square)
    if piece is None:
        return 0.0

    atk_val = _PIECE_VALUE.get(piece.piece_type, 0)

    if board.is_capture(move):
        # Determine victim value
        if board.is_en_passant(move):
            vic_val = 100  # pawn
        else:
            victim = board.piece_at(move.to_square)
            vic_val = _PIECE_VALUE.get(victim.piece_type, 0) if victim else 0

        if atk_val > vic_val:
            score = 1.0   # sacrifice
        elif atk_val == vic_val:
            score = 0.4   # even exchange
        else:
            score = 0.75  # winning capture
    elif board.gives_check(move):
        score = 0.7
    elif piece.piece_type == chess.PAWN:
        score = 0.2
    else:
        score = 0.05  # quiet piece development / repositioning

    return score


def _score_aggression_match(
    move: chess.Move, board: chess.Board, profile: StyleProfile
) -> float:
    """
    0–1: how well this move's aggression level matches the profile.
    Uses a Gaussian-like closeness measure: 1.0 when perfectly matched, lower further away.
    """
    move_agg = _move_aggression(move, board)
    distance = abs(move_agg - profile.aggression_index)
    # Gaussian falloff: at distance 0 → 1.0, at distance 1 → ~0.37
    return math.exp(-2.5 * distance)


def _board_tension(board: chess.Board) -> float:
    """
    Normalised board tension (0–1): fraction of pieces that are currently
    attacked by the opponent. High tension = complex tactical position.
    """
    total_pieces = len(board.piece_map())
    if total_pieces == 0:
        return 0.0
    attacked = sum(
        1
        for sq, piece in board.piece_map().items()
        if board.is_attacked_by(not piece.color, sq)
    )
    return min(1.0, attacked / max(total_pieces, 1))


def _score_complexity_preference(
    board: chess.Board, profile: StyleProfile
) -> float:
    """
    0–1: how well the current position's complexity matches the player's style.
    Aggressive players prefer complex (high-tension) positions.
    This is position-level, not move-level — same value for all candidates.
    """
    tension = _board_tension(board)
    distance = abs(tension - profile.aggression_index)
    return math.exp(-2.5 * distance)


def _score_time_accuracy(
    move: chess.Move,
    board: chess.Board,
    profile: StyleProfile,
    engine_score: float,
) -> float:
    """
    0–1: time-adjusted accuracy score.

    Models the player's tendency to make inaccuracies:
    - avg_centipawn_loss drives the noise level (higher CPL → more likely to
      deviate from the engine's top choice)
    - time_pressure_accuracy_drop adds extra noise in the endgame (move 30+)
      as a proxy for clock pressure
    """
    avg_cpl = profile.accuracy.avg_centipawn_loss
    # Normalise CPL: 0 CPL → 0 noise, 100 CPL → 1.0 noise
    noise = min(1.0, avg_cpl / 100.0)

    # Late game → simulate time pressure degradation
    if board.fullmove_number >= 30:
        pressure_drop = profile.time_signature.time_pressure_accuracy_drop
        noise = min(1.0, noise + pressure_drop / 200.0)

    # Accuracy = engine soundness attenuated by noise
    # Noise pulls the score toward 0.5 (random), away from engine_score
    return engine_score * (1 - noise) + 0.5 * noise


# ---------------------------------------------------------------------------
# Softmax
# ---------------------------------------------------------------------------

def _softmax_temperature(profile: StyleProfile) -> float:
    """
    Adaptive temperature for softmax sampling.

    Higher CPL players make less optimal choices → higher temperature (more
    random sampling from the top-N candidates).
    Range: ~0.6 (very accurate) to ~1.6 (blunder-prone).
    """
    avg_cpl = profile.accuracy.avg_centipawn_loss
    # 0 CPL → 0.6, 100 CPL → 1.1, 200 CPL → 1.6
    return 0.6 + min(1.0, avg_cpl / 200.0)


def _softmax(values: list[float], temperature: float) -> list[float]:
    """Numerically stable softmax with temperature scaling."""
    scaled = [v / temperature for v in values]
    max_val = max(scaled)
    exps = [math.exp(v - max_val) for v in scaled]
    total = sum(exps)
    return [e / total for e in exps]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _score_candidate(
    move: chess.Move,
    board: chess.Board,
    profile: StyleProfile,
    engine_score: float,
) -> tuple[float, StyleScores]:
    """Score one candidate against the StyleProfile. Returns (total, breakdown)."""
    opening_affinity = _score_opening_affinity(move, board, profile, engine_score)
    aggression_match = _score_aggression_match(move, board, profile)
    complexity_preference = _score_complexity_preference(board, profile)
    time_adjusted_accuracy = _score_time_accuracy(move, board, profile, engine_score)

    scores = StyleScores(
        opening_affinity=round(opening_affinity, 3),
        aggression_match=round(aggression_match, 3),
        complexity_preference=round(complexity_preference, 3),
        time_adjusted_accuracy=round(time_adjusted_accuracy, 3),
    )
    total = (
        scores.opening_affinity * 0.3
        + scores.aggression_match * 0.3
        + scores.complexity_preference * 0.2
        + scores.time_adjusted_accuracy * 0.2
    )
    return total, scores


async def select_move(
    board: chess.Board,
    profile: StyleProfile,
    stockfish_path: str,
    think_time: float = 0.1,
) -> tuple[chess.Move, StyleScores]:
    """
    Pick the next move for the clone.

    Args:
        board: Current position (will not be mutated).
        profile: The target player's StyleProfile.
        stockfish_path: Path to the Stockfish binary.
        think_time: Seconds Stockfish spends analysing per candidate.

    Returns:
        (chosen_move, style_scores_for_that_move)
    """
    skill_level = _rating_to_skill_level(profile.avg_rating)
    top_n = _skill_top_n(skill_level)
    think_time = _skill_think_time(skill_level)
    engine = await _get_engine(stockfish_path, skill_level)

    # Run multipv analysis in a thread (Stockfish is blocking)
    analysis: list[chess.engine.InfoDict] = await asyncio.to_thread(
        engine.analyse,
        board,
        chess.engine.Limit(time=think_time),
        multipv=top_n,
    )

    # --- Fallback ---
    def _fallback() -> tuple[chess.Move, StyleScores]:
        move = random.choice(list(board.legal_moves))
        return move, StyleScores(
            opening_affinity=0.5,
            aggression_match=0.5,
            complexity_preference=0.5,
            time_adjusted_accuracy=0.5,
        )

    if not analysis:
        return _fallback()

    # --- Extract (move, centipawn_score) from each pv ---
    raw: list[tuple[chess.Move, float]] = []
    for info in analysis:
        pv = info.get("pv")
        score = info.get("score")
        if not pv or score is None:
            continue
        cp = score.white().score(mate_score=10_000) or 0
        raw.append((pv[0], float(cp)))

    if not raw:
        return _fallback()

    # --- Normalise engine scores to [0, 1] (best candidate = 1.0) ---
    # From the perspective of the side to move (not always White)
    if board.turn == chess.BLACK:
        raw = [(m, -cp) for m, cp in raw]  # flip: Black wants low White-eval

    best_cp = max(cp for _, cp in raw)
    worst_cp = min(cp for _, cp in raw)
    span = max(best_cp - worst_cp, 1.0)
    normalised = [(m, (cp - worst_cp) / span) for m, cp in raw]

    # --- Score candidates against the profile ---
    candidates: list[tuple[chess.Move, float, StyleScores]] = []
    for move, norm_score in normalised:
        total, style_scores = _score_candidate(move, board, profile, norm_score)
        candidates.append((move, total, style_scores))

    # --- Softmax-sample with adaptive temperature ---
    temperature = _softmax_temperature(profile)
    scores_only = [c[1] for c in candidates]
    probs = _softmax(scores_only, temperature)
    chosen_idx = random.choices(range(len(candidates)), weights=probs, k=1)[0]
    chosen_move, _, chosen_style_scores = candidates[chosen_idx]

    return chosen_move, chosen_style_scores


async def shutdown_engine() -> None:
    """Gracefully quit the Stockfish subprocess."""
    global _engine
    if _engine is not None:
        await asyncio.to_thread(_engine.quit)
        _engine = None
