"""
# backend/models.py
Pydantic v2 models shared across the backend.
These are the canonical data shapes — all API responses and internal
functions should use these types.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Style profile
# ---------------------------------------------------------------------------

class OpeningDNA(BaseModel):
    """Frequency map of ECO codes and average depth of book deviation."""
    eco_frequency: dict[str, float] = Field(default_factory=dict)
    avg_deviation_depth: float = 0.0
    # First-move repertoire (UCI → frequency), built during profiling.
    # Used by move_engine.py to score opening affinity without a book file.
    white_first_moves: dict[str, float] = Field(default_factory=dict)
    # Black's responses keyed by White's first move (e.g. "e2e4" → {"e7e5": 0.6})
    black_responses: dict[str, dict[str, float]] = Field(default_factory=dict)


class AccuracyProfile(BaseModel):
    avg_centipawn_loss: float = 0.0
    blunder_rate: float = 0.0   # blunders per game
    mistake_rate: float = 0.0   # mistakes per game


class TimeSignature(BaseModel):
    avg_move_time_ms: float = 0.0
    time_pressure_accuracy_drop: float = 0.0  # extra CPL when < 30s on clock


class StyleProfile(BaseModel):
    username: str
    games_analyzed: int = 0
    avg_rating: int = 1500  # average Lichess rating across analyzed games
    opening_dna: OpeningDNA = Field(default_factory=OpeningDNA)
    aggression_index: float = Field(0.5, ge=0.0, le=1.0)
    accuracy: AccuracyProfile = Field(default_factory=AccuracyProfile)
    time_signature: TimeSignature = Field(default_factory=TimeSignature)
    endgame_simplification_rate: float = Field(0.5, ge=0.0, le=1.0)


# ---------------------------------------------------------------------------
# Game / move protocol (WebSocket messages)
# ---------------------------------------------------------------------------

class ClientMove(BaseModel):
    type: str = "move"
    uci: str  # e.g. "e2e4"


class StyleScores(BaseModel):
    opening_affinity: float
    aggression_match: float
    complexity_preference: float
    time_adjusted_accuracy: float


class ServerMove(BaseModel):
    type: str = "move"
    uci: str
    fen: str
    style_scores: StyleScores


class GameOver(BaseModel):
    type: str = "game_over"
    result: str          # "1-0" | "0-1" | "1/2-1/2"
    reason: str          # "checkmate" | "stalemate" | "resignation" | …


class GameReady(BaseModel):
    """Sent immediately after WebSocket accept, before any moves."""
    type: str = "ready"
    fen: str                    # starting FEN (after clone's move if user is Black)
    your_color: str             # "white" | "black"


class ErrorMessage(BaseModel):
    type: str = "error"
    message: str


# ---------------------------------------------------------------------------
# API responses
# ---------------------------------------------------------------------------

class ProfileResponse(BaseModel):
    profile: StyleProfile


class HealthResponse(BaseModel):
    status: str = "ok"
