"""
# backend/main.py
FastAPI entry point.

Routes:
  GET  /health                          → liveness check
  POST /profile/{username}             → fetch Lichess games + build StyleProfile
  GET  /profile/{username}             → return cached StyleProfile
  WS   /play/{username}?color=white    → live game WebSocket
"""

from __future__ import annotations

import json
import os
from contextlib import asynccontextmanager

import redis.asyncio as aioredis
from fastapi import FastAPI, HTTPException, WebSocket
from fastapi.middleware.cors import CORSMiddleware

from game_server import run_game
from lichess import LichessError, fetch_games_pgn
from models import HealthResponse, ProfileResponse, StyleProfile
from move_engine import shutdown_engine
from profiler import build_profile

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379")
PROFILE_TTL = 60 * 60 * 6  # 6 hours

_redis: aioredis.Redis | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _redis
    _redis = aioredis.from_url(REDIS_URL, decode_responses=True)
    yield
    await _redis.aclose()
    await shutdown_engine()


app = FastAPI(title="ChessClone API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],  # SvelteKit dev server
    allow_methods=["*"],
    allow_headers=["*"],
)


def _cache_key(username: str) -> str:
    return f"profile:{username.lower()}"


async def _get_cached_profile(username: str) -> StyleProfile | None:
    assert _redis is not None
    raw = await _redis.get(_cache_key(username))
    if raw is None:
        return None
    return StyleProfile.model_validate_json(raw)


async def _set_cached_profile(profile: StyleProfile) -> None:
    assert _redis is not None
    await _redis.setex(
        _cache_key(profile.username),
        PROFILE_TTL,
        profile.model_dump_json(),
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse()


@app.post("/profile/{username}", response_model=ProfileResponse)
async def create_profile(username: str) -> ProfileResponse:
    """Fetch games from Lichess, build a StyleProfile, cache it, return it."""
    try:
        pgn_text = await fetch_games_pgn(username)
    except LichessError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    profile = build_profile(username, pgn_text)
    await _set_cached_profile(profile)
    return ProfileResponse(profile=profile)


@app.get("/profile/{username}", response_model=ProfileResponse)
async def get_profile(username: str) -> ProfileResponse:
    """Return a cached StyleProfile (call POST first to build it)."""
    profile = await _get_cached_profile(username)
    if profile is None:
        raise HTTPException(
            status_code=404,
            detail=f"No profile for '{username}'. Call POST /profile/{username} first.",
        )
    return ProfileResponse(profile=profile)


@app.websocket("/play/{username}")
async def play(websocket: WebSocket, username: str, color: str = "white") -> None:
    """WebSocket endpoint for a live game against the clone."""
    profile = await _get_cached_profile(username)
    if profile is None:
        await websocket.accept()
        await websocket.send_json(
            {"type": "error", "message": f"Profile for '{username}' not found."}
        )
        await websocket.close()
        return

    user_plays_white = color.lower() != "black"
    await run_game(websocket, profile, user_plays_white=user_plays_white)
