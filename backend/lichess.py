"""
# backend/lichess.py
Fetches a player's recent games from the Lichess public API.
Returns raw PGN text; parsing happens in profiler.py.
"""

from __future__ import annotations

import httpx

LICHESS_API_BASE = "https://lichess.org/api"
DEFAULT_MAX_GAMES = 100


class LichessError(Exception):
    """Raised when the Lichess API returns an unexpected response."""


async def fetch_games_pgn(username: str, max_games: int = DEFAULT_MAX_GAMES) -> str:
    """
    Download up to *max_games* games for *username* as a single PGN string.

    Lichess returns newline-delimited PGN — multiple games concatenated.
    We request clocks so the profiler can build a TimeSignature.

    Raises:
        LichessError: on non-200 HTTP status or network failure.
    """
    url = f"{LICHESS_API_BASE}/games/user/{username}"
    params = {
        "max": max_games,
        "pgnInJson": "false",
        "clocks": "true",
        "evals": "true",      # include [%eval ...] comments — needed for CPL
        "opening": "true",    # includes ECO + opening name in PGN headers
        "perfType": "rapid,classical,blitz",  # skip bullet/ultrabullet noise
        "analysed": "true",   # only games with computer analysis (have evals)
    }
    headers = {
        # Lichess requires Accept header for plain PGN
        "Accept": "application/x-chess-pgn",
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.get(url, params=params, headers=headers)
        except httpx.RequestError as exc:
            raise LichessError(f"Network error fetching games: {exc}") from exc

    if response.status_code == 404:
        raise LichessError(f"Lichess user '{username}' not found.")
    if response.status_code != 200:
        raise LichessError(
            f"Lichess API error {response.status_code}: {response.text[:200]}"
        )

    pgn_text = response.text.strip()
    if not pgn_text:
        raise LichessError(f"No games found for user '{username}'.")

    return pgn_text
