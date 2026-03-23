"""
# backend/profiler.py
Parses a raw PGN string (from lichess.py) and builds a StyleProfile.

All heavy computation happens here — move_engine.py only consumes the result.
"""

from __future__ import annotations

import io
import re
from collections import Counter, defaultdict

import chess
import chess.pgn

from models import (
    AccuracyProfile,
    OpeningDNA,
    StyleProfile,
    TimeSignature,
)

# Centipawn loss thresholds (matching Lichess definitions)
_BLUNDER_CPL = 300
_MISTAKE_CPL = 100

# Centipawn value used for forced mates (large but finite so averages stay sane)
_MATE_CP = 1000

# Clock comment pattern: { [%clk 0:01:23] }
_CLOCK_RE = re.compile(r"\[%clk (\d+):(\d+):(\d+)\]")

# Eval comment pattern: [%eval 0.42] or [%eval #3] (forced mate)
_EVAL_RE = re.compile(r"\[%eval (#-?\d+|[+-]?\d+\.?\d*)\]")

# Piece values for sacrifice detection (centipawns)
_PIECE_VALUE = {
    chess.PAWN: 100,
    chess.KNIGHT: 300,
    chess.BISHOP: 300,
    chess.ROOK: 500,
    chess.QUEEN: 900,
    chess.KING: 0,
}


def _parse_clock_ms(comment: str) -> int | None:
    """Extract remaining clock time in milliseconds from a PGN comment."""
    m = _CLOCK_RE.search(comment)
    if not m:
        return None
    h, mn, s = int(m.group(1)), int(m.group(2)), int(m.group(3))
    return (h * 3600 + mn * 60 + s) * 1000


def _parse_eval(comment: str) -> int | None:
    """
    Extract centipawn evaluation from a PGN comment.

    Handles:
      [%eval 0.42]   → 42 centipawns (from White's perspective)
      [%eval -1.30]  → -130 centipawns
      [%eval #3]     → +_MATE_CP  (forced mate for the side to move)
      [%eval #-3]    → -_MATE_CP  (forced mate against the side to move)
    """
    m = _EVAL_RE.search(comment)
    if not m:
        return None
    raw = m.group(1)
    if raw.startswith("#"):
        # Forced mate — sign tells us who is mating
        return _MATE_CP if int(raw[1:]) > 0 else -_MATE_CP
    try:
        return int(float(raw) * 100)
    except ValueError:
        return None


def _position_key(board: chess.Board) -> str:
    """Board position key — piece placement + side to move (ignores clocks/ep)."""
    parts = board.fen().split()
    return f"{parts[0]} {parts[1]}"


# ---------------------------------------------------------------------------
# Two-pass helpers for opening deviation depth
# ---------------------------------------------------------------------------

def _collect_game_positions(
    game: chess.pgn.Game,
    user_is_white: bool,
    max_ply: int = 30,
) -> list[str]:
    """
    Return the sequence of position keys seen in a game, from the user's
    perspective, up to *max_ply* half-moves. Used in the first pass.
    """
    board = game.board()
    positions: list[str] = [_position_key(board)]
    ply = 0
    for node in game.mainline():
        if ply >= max_ply:
            break
        board.push(node.move)
        positions.append(_position_key(board))
        ply += 1
    return positions


def _compute_deviation_depth(
    game: chess.pgn.Game,
    user_is_white: bool,
    position_freq: Counter[str],
    min_freq: int = 2,
    max_ply: int = 30,
) -> int:
    """
    Walk through the game move by move. Return the ply at which the resulting
    position has been seen fewer than *min_freq* times in the corpus.

    A position seen in only 1 game (this game itself) means the player has
    deviated from any previously observed line — their "book" ran out.
    """
    board = game.board()
    for ply, node in enumerate(game.mainline()):
        if ply >= max_ply:
            return max_ply
        board.push(node.move)
        key = _position_key(board)
        if position_freq[key] < min_freq:
            return ply  # first unseen position = deviation point
    return max_ply  # never deviated within max_ply


# ---------------------------------------------------------------------------
# Main profiler
# ---------------------------------------------------------------------------

def build_profile(username: str, pgn_text: str) -> StyleProfile:
    """
    Parse *pgn_text* and return a StyleProfile for *username*.

    The PGN may contain games where the user plays either colour —
    we track only their moves.

    Two-pass algorithm:
      Pass 1: collect position frequencies across all games (for opening depth).
      Pass 2: full stat extraction per game.
    """
    pgn_io = io.StringIO(pgn_text)
    uname = username.lower()

    # -----------------------------------------------------------------------
    # Pass 1: collect all positions and identify which games involve the user
    # -----------------------------------------------------------------------
    games: list[chess.pgn.Game] = []
    user_colors: list[bool] = []  # True = user is White in that game

    while True:
        game = chess.pgn.read_game(pgn_io)
        if game is None:
            break
        headers = game.headers
        white = headers.get("White", "").lower()
        black = headers.get("Black", "").lower()
        if uname not in (white, black):
            continue
        user_is_white = uname == white
        games.append(game)
        user_colors.append(user_is_white)

    if not games:
        # Return an empty profile rather than crashing
        return StyleProfile(username=username, games_analyzed=0)

    # Count how many times each position appears across all user games
    position_freq: Counter[str] = Counter()
    for game, user_is_white in zip(games, user_colors):
        for key in _collect_game_positions(game, user_is_white):
            position_freq[key] += 1

    # -----------------------------------------------------------------------
    # Pass 2: per-game stat extraction
    # -----------------------------------------------------------------------
    eco_counter: Counter[str] = Counter()
    deviation_depths: list[int] = []
    cpl_list: list[float] = []
    blunders = 0
    mistakes = 0
    move_times_ms: list[float] = []
    ratings: list[int] = []

    # For time-pressure CPL delta we track CPL split by clock state
    normal_cpls: list[float] = []
    pressure_cpls: list[float] = []  # moves made with < 30s remaining

    pawn_advances = 0
    checks_given = 0
    sacrifices = 0     # captures where attacker's value > victim's value
    total_moves = 0
    piece_trades = 0   # captures of equal piece value (simplification proxy)
    games_analyzed = 0

    # First-move repertoire: UCI → count
    white_first_counter: Counter[str] = Counter()
    # Black's first responses, keyed by White's first move: white_uci → black_uci → count
    black_response_counter: dict[str, Counter[str]] = defaultdict(Counter)

    for game, user_is_white in zip(games, user_colors):
        headers = game.headers
        games_analyzed += 1

        # --- Rating ---
        elo_key = "WhiteElo" if user_is_white else "BlackElo"
        try:
            ratings.append(int(headers.get(elo_key, 0)))
        except ValueError:
            pass

        # --- Opening DNA ---
        eco = headers.get("ECO", "")
        if eco:
            eco_counter[eco] += 1

        # --- Opening deviation depth (from pass 1 data) ---
        depth = _compute_deviation_depth(game, user_is_white, position_freq)
        deviation_depths.append(depth)

        # --- Per-move stats ---
        board = game.board()
        prev_clock_ms: int | None = None
        # prev_eval tracks the eval AFTER the last move (= eval BEFORE this move)
        prev_eval: int | None = None

        for node in game.mainline():
            move = node.move
            color = board.turn  # color BEFORE the move
            is_user_move = (color == chess.WHITE) == user_is_white

            comment = node.comment or ""
            clock_ms = _parse_clock_ms(comment)
            eval_cp = _parse_eval(comment)

            if is_user_move:
                total_moves += 1

                # --- First-move repertoire ---
                if board.fullmove_number == 1:
                    if user_is_white:
                        white_first_counter[move.uci()] += 1
                    else:
                        # Black's response — need the move White just played.
                        # The move stack has one entry (White's first move).
                        if board.move_stack:
                            white_first_uci = board.peek().uci()
                            black_response_counter[white_first_uci][move.uci()] += 1

                # --- CPL ---
                # prev_eval = eval of position BEFORE this move (from White's PoV)
                # eval_cp   = eval of position AFTER this move  (from White's PoV)
                if prev_eval is not None and eval_cp is not None:
                    if user_is_white:
                        # White wants eval to go up; loss = prev - curr (if positive)
                        cpl = max(0, prev_eval - eval_cp)
                    else:
                        # Black wants eval to go down; loss = curr - prev (if positive)
                        cpl = max(0, eval_cp - prev_eval)

                    cpl_list.append(float(cpl))
                    if cpl >= _BLUNDER_CPL:
                        blunders += 1
                    elif cpl >= _MISTAKE_CPL:
                        mistakes += 1

                    # Split CPL by time pressure
                    if clock_ms is not None and clock_ms < 30_000:
                        pressure_cpls.append(float(cpl))
                    else:
                        normal_cpls.append(float(cpl))

                # --- Move time ---
                if prev_clock_ms is not None and clock_ms is not None:
                    elapsed = prev_clock_ms - clock_ms
                    if 0 <= elapsed < 600_000:  # sanity-check (< 10 min per move)
                        move_times_ms.append(float(elapsed))

                # --- Aggression signals ---
                piece = board.piece_at(move.from_square)
                if piece:
                    # Pawn advances
                    if piece.piece_type == chess.PAWN:
                        pawn_advances += 1

                    # Checks given
                    if board.gives_check(move):
                        checks_given += 1

                    # Captures
                    if board.is_capture(move):
                        victim_sq = move.to_square
                        # En-passant: victim is not on to_square
                        if board.is_en_passant(move):
                            victim_sq = (
                                move.to_square - 8
                                if color == chess.WHITE
                                else move.to_square + 8
                            )
                        victim = board.piece_at(victim_sq)
                        if victim:
                            atk_val = _PIECE_VALUE.get(piece.piece_type, 0)
                            vic_val = _PIECE_VALUE.get(victim.piece_type, 0)
                            if atk_val == vic_val:
                                piece_trades += 1
                            elif atk_val > vic_val:
                                sacrifices += 1  # gave up more material

            prev_eval = eval_cp
            prev_clock_ms = clock_ms
            board.push(move)

    # -----------------------------------------------------------------------
    # Aggregate
    # -----------------------------------------------------------------------
    total_games = games_analyzed or 1

    eco_frequency = {
        eco: count / total_games for eco, count in eco_counter.most_common(10)
    }
    avg_deviation_depth = (
        sum(deviation_depths) / len(deviation_depths) if deviation_depths else 0.0
    )

    avg_cpl = sum(cpl_list) / len(cpl_list) if cpl_list else 0.0
    blunder_rate = blunders / total_games
    mistake_rate = mistakes / total_games

    avg_move_time = (
        sum(move_times_ms) / len(move_times_ms) if move_times_ms else 0.0
    )

    # Time-pressure accuracy DROP: extra CPL incurred when clock < 30s
    avg_normal_cpl = sum(normal_cpls) / len(normal_cpls) if normal_cpls else avg_cpl
    avg_pressure_cpl = sum(pressure_cpls) / len(pressure_cpls) if pressure_cpls else avg_normal_cpl
    time_pressure_drop = max(0.0, avg_pressure_cpl - avg_normal_cpl)

    # Aggression index: weighted sum of pawn advances, checks, and sacrifices
    # Each is normalised per move so different game counts don't skew the result
    safe_moves = max(total_moves, 1)
    pawn_rate = pawn_advances / safe_moves         # ~0.10–0.25 typical
    check_rate = checks_given / safe_moves         # ~0.02–0.08 typical
    sac_rate = sacrifices / safe_moves             # ~0.00–0.03 typical

    # Scale each component to [0,1] range with empirically chosen caps
    pawn_score = min(1.0, pawn_rate / 0.25)
    check_score = min(1.0, check_rate / 0.08)
    sac_score = min(1.0, sac_rate / 0.03)

    aggression = pawn_score * 0.5 + check_score * 0.3 + sac_score * 0.2

    # Endgame simplification rate: equal-value piece exchanges per move
    simplification = min(1.0, (piece_trades / safe_moves) / 0.05)

    # First-move repertoire: normalise counts to frequencies
    total_white_games = sum(white_first_counter.values()) or 1
    white_first_moves = {
        uci: round(count / total_white_games, 3)
        for uci, count in white_first_counter.most_common(5)
    }
    black_responses: dict[str, dict[str, float]] = {}
    for white_uci, resp_counter in black_response_counter.items():
        total = sum(resp_counter.values()) or 1
        black_responses[white_uci] = {
            uci: round(count / total, 3)
            for uci, count in resp_counter.most_common(5)
        }

    valid_ratings = [r for r in ratings if r > 0]
    avg_rating = round(sum(valid_ratings) / len(valid_ratings)) if valid_ratings else 1500

    return StyleProfile(
        username=username,
        games_analyzed=games_analyzed,
        avg_rating=avg_rating,
        opening_dna=OpeningDNA(
            eco_frequency=eco_frequency,
            avg_deviation_depth=round(avg_deviation_depth, 1),
            white_first_moves=white_first_moves,
            black_responses=black_responses,
        ),
        aggression_index=round(min(1.0, aggression), 3),
        accuracy=AccuracyProfile(
            avg_centipawn_loss=round(avg_cpl, 1),
            blunder_rate=round(blunder_rate, 3),
            mistake_rate=round(mistake_rate, 3),
        ),
        time_signature=TimeSignature(
            avg_move_time_ms=round(avg_move_time, 1),
            time_pressure_accuracy_drop=round(time_pressure_drop, 1),
        ),
        endgame_simplification_rate=round(min(1.0, simplification), 3),
    )
