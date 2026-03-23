/**
 * # frontend/src/lib/api.ts
 * Typed client for the ChessClone backend.
 *
 * All types mirror the Pydantic models in backend/models.py.
 */

const API_BASE = import.meta.env.PUBLIC_API_URL ?? "http://localhost:8000";
const WS_BASE = API_BASE.replace(/^http/, "ws");

// ---------------------------------------------------------------------------
// Types (mirror backend/models.py)
// ---------------------------------------------------------------------------

export interface OpeningDNA {
  eco_frequency: Record<string, number>;
  avg_deviation_depth: number;
}

export interface AccuracyProfile {
  avg_centipawn_loss: number;
  blunder_rate: number;
  mistake_rate: number;
}

export interface TimeSignature {
  avg_move_time_ms: number;
  time_pressure_accuracy_drop: number;
}

export interface StyleProfile {
  username: string;
  games_analyzed: number;
  opening_dna: OpeningDNA;
  aggression_index: number;
  accuracy: AccuracyProfile;
  time_signature: TimeSignature;
  endgame_simplification_rate: number;
}

export interface ProfileResponse {
  profile: StyleProfile;
}

export interface StyleScores {
  opening_affinity: number;
  aggression_match: number;
  complexity_preference: number;
  time_adjusted_accuracy: number;
}

// WebSocket message types (from server)
export type ServerMessage =
  | { type: "ready"; fen: string; your_color: "white" | "black" }
  | { type: "move"; uci: string; fen: string; style_scores: StyleScores }
  | { type: "game_over"; result: string; reason: string }
  | { type: "error"; message: string };

// WebSocket message types (to server)
export interface ClientMove {
  type: "move";
  uci: string;
}

// ---------------------------------------------------------------------------
// REST helpers
// ---------------------------------------------------------------------------

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(body.detail ?? `HTTP ${res.status}`);
  }
  return res.json() as Promise<T>;
}

/** Fetch Lichess games and build a StyleProfile (slow — hits Lichess API). */
export async function buildProfile(username: string): Promise<StyleProfile> {
  const data = await apiFetch<ProfileResponse>(`/profile/${username}`, {
    method: "POST",
  });
  return data.profile;
}

/** Return a previously built StyleProfile from cache. */
export async function getProfile(username: string): Promise<StyleProfile> {
  const data = await apiFetch<ProfileResponse>(`/profile/${username}`);
  return data.profile;
}

// ---------------------------------------------------------------------------
// WebSocket helper
// ---------------------------------------------------------------------------

/**
 * Open a game WebSocket for *username*.
 * Returns the raw WebSocket — the caller manages messages.
 */
export function openGameSocket(
  username: string,
  color: "white" | "black" = "white"
): WebSocket {
  return new WebSocket(`${WS_BASE}/play/${username}?color=${color}`);
}
