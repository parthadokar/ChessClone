"""
# backend/game_server.py
WebSocket game loop.

Protocol (from CLAUDE.md + extensions):
  Server → Client: { "type": "ready",     "fen": "...", "your_color": "white" }
  Client → Server: { "type": "move",      "uci": "e2e4" }
  Server → Client: { "type": "move",      "uci": "e7e5", "fen": "...", "style_scores": {...} }
  Server → Client: { "type": "game_over", "result": "1-0", "reason": "checkmate" }
  Server → Client: { "type": "error",     "message": "..." }
"""

from __future__ import annotations

import asyncio
import json
import logging
import os

import chess
from fastapi import WebSocket, WebSocketDisconnect

from models import (
    ClientMove,
    ErrorMessage,
    GameOver,
    GameReady,
    ServerMove,
    StyleProfile,
)
from move_engine import select_move, shutdown_engine

log = logging.getLogger(__name__)

STOCKFISH_PATH = os.environ.get("STOCKFISH_PATH", "/usr/bin/stockfish")

# Maximum seconds we'll wait for Stockfish to reply before giving up
ENGINE_TIMEOUT = 15.0


def _game_over_result(board: chess.Board) -> GameOver | None:
    """Return a GameOver message if the game has ended, else None."""
    if not board.is_game_over():
        return None
    outcome = board.outcome()
    if outcome is None:
        return None
    reason_map = {
        chess.Termination.CHECKMATE: "checkmate",
        chess.Termination.STALEMATE: "stalemate",
        chess.Termination.INSUFFICIENT_MATERIAL: "insufficient material",
        chess.Termination.SEVENTYFIVE_MOVES: "75-move rule",
        chess.Termination.FIVEFOLD_REPETITION: "fivefold repetition",
        chess.Termination.FIFTY_MOVES: "50-move rule",
        chess.Termination.THREEFOLD_REPETITION: "threefold repetition",
    }
    reason = reason_map.get(outcome.termination, "unknown")
    return GameOver(result=outcome.result(), reason=reason)


async def _clone_move(
    board: chess.Board,
    profile: StyleProfile,
    websocket: WebSocket,
) -> bool:
    """
    Ask the engine for a move, push it, and send it to the client.

    Returns True if the move was made successfully, False on engine failure.
    On failure a descriptive error is sent to the client and the engine
    subprocess is restarted so the next game works cleanly.
    """
    try:
        move, style_scores = await asyncio.wait_for(
            select_move(board, profile, STOCKFISH_PATH),
            timeout=ENGINE_TIMEOUT,
        )
    except asyncio.TimeoutError:
        log.error("Stockfish timed out after %.0fs", ENGINE_TIMEOUT)
        err = ErrorMessage(message="Engine timed out — please start a new game.")
        await websocket.send_text(err.model_dump_json())
        await shutdown_engine()   # force-restart on next game
        return False
    except Exception as exc:
        log.exception("Engine error: %s", exc)
        err = ErrorMessage(message=f"Engine error: {exc}")
        await websocket.send_text(err.model_dump_json())
        await shutdown_engine()
        return False

    board.push(move)
    response = ServerMove(uci=move.uci(), fen=board.fen(), style_scores=style_scores)
    await websocket.send_text(response.model_dump_json())
    return True


async def run_game(
    websocket: WebSocket,
    profile: StyleProfile,
    user_plays_white: bool = True,
) -> None:
    """
    Main WebSocket game loop.

    State flow:
      1. Accept connection
      2. If user is Black: clone makes opening move
      3. Send "ready" message with current FEN and user's colour
      4. Loop: receive user move → validate → clone replies → check game over
    """
    await websocket.accept()

    board = chess.Board()
    your_color = "white" if user_plays_white else "black"

    # --- Clone's opening move (only when user plays Black) ---
    if not user_plays_white:
        ok = await _clone_move(board, profile, websocket)
        if not ok:
            await websocket.close()
            return
        # Check immediate game-over (extremely unlikely on move 1, but correct)
        over = _game_over_result(board)
        if over:
            await websocket.send_text(over.model_dump_json())
            await websocket.close()
            return

    # --- Signal that the game is ready ---
    ready = GameReady(fen=board.fen(), your_color=your_color)
    await websocket.send_text(ready.model_dump_json())

    # --- Main game loop ---
    try:
        while True:
            # Receive and parse user's move
            try:
                raw = await websocket.receive_text()
            except WebSocketDisconnect:
                return

            try:
                data = json.loads(raw)
                client_msg = ClientMove(**data)
            except Exception:
                err = ErrorMessage(message="Invalid message format — expected {type, uci}.")
                await websocket.send_text(err.model_dump_json())
                continue

            # Validate move legality
            try:
                user_move = chess.Move.from_uci(client_msg.uci)
                if user_move not in board.legal_moves:
                    raise ValueError(f"Illegal move: {client_msg.uci}")
                board.push(user_move)
            except ValueError as exc:
                err = ErrorMessage(message=str(exc))
                await websocket.send_text(err.model_dump_json())
                continue

            # Check game over after user's move
            over = _game_over_result(board)
            if over:
                await websocket.send_text(over.model_dump_json())
                return

            # Clone replies
            ok = await _clone_move(board, profile, websocket)
            if not ok:
                # Engine failed — stop the game; client already received error msg
                return

            # Check game over after clone's move
            over = _game_over_result(board)
            if over:
                await websocket.send_text(over.model_dump_json())
                return

    except WebSocketDisconnect:
        pass  # client closed tab / navigated away
