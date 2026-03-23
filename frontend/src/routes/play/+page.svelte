<script lang="ts">
  /**
   * # frontend/src/routes/play/+page.svelte
   * Live game page — colour picker → WebSocket game loop.
   *
   * State machine:
   *   idle → setup (colour picker) → connecting → playing → game_over
   *
   * New in this version:
   *   - Colour choice screen before connecting
   *   - Board orientation flips when playing as Black
   *   - Handles the "ready" message from the server (tells us when the
   *     clone has made its opening move and we can start playing)
   *   - Stockfish timeout/crash errors are surfaced with a "New game" button
   */
  import { goto } from "$app/navigation";
  import Board from "$lib/Board.svelte";
  import { openGameSocket, type ServerMessage, type StyleScores } from "$lib/api";
  import { profile, username } from "$lib/stores";
  import { onDestroy, onMount } from "svelte";

  const STARTING_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1";

  // ---- game state ----
  let status = $state<"idle" | "setup" | "connecting" | "playing" | "game_over">("idle");
  let userColor = $state<"white" | "black">("white");
  let fen = $state(STARTING_FEN);
  let gameResult = $state("");
  let gameReason = $state("");
  let lastStyleScores = $state<StyleScores | null>(null);
  let errorMsg = $state("");
  let boardLocked = $state(true);
  let fatalError = $state(false);   // true when the engine crashed mid-game

  let socket: WebSocket | null = null;

  onMount(() => {
    if (!$profile) { goto("/"); return; }
    status = "setup";
  });

  onDestroy(() => socket?.close());

  // ---- colour picker ----
  function chooseColor(color: "white" | "black") {
    userColor = color;
    connect();
  }

  // ---- WebSocket ----
  function connect() {
    status = "connecting";
    boardLocked = true;
    fatalError = false;
    fen = STARTING_FEN;
    lastStyleScores = null;
    errorMsg = "";

    socket = openGameSocket($username, userColor);

    socket.onmessage = (event: MessageEvent) => {
      const msg: ServerMessage = JSON.parse(event.data);

      if (msg.type === "ready") {
        // Server has finished any opening moves and is waiting for us.
        fen = msg.fen;
        status = "playing";
        boardLocked = false;

      } else if (msg.type === "move") {
        // Clone's reply to our move.
        fen = msg.fen;
        lastStyleScores = msg.style_scores;
        boardLocked = false;

      } else if (msg.type === "game_over") {
        status = "game_over";
        gameResult = msg.result;
        gameReason = msg.reason;
        boardLocked = true;

      } else if (msg.type === "error") {
        errorMsg = msg.message;
        // If the engine crashed the message will say so — treat as fatal
        fatalError = msg.message.includes("Engine") || msg.message.includes("timed out");
        boardLocked = fatalError;  // lock board on fatal; unlock on recoverable
      }
    };

    socket.onerror = () => {
      errorMsg = "WebSocket connection failed — is the backend running?";
      fatalError = true;
      status = "idle";
    };
  }

  function handleMove(uci: string) {
    boardLocked = true;
    errorMsg = "";
    socket?.send(JSON.stringify({ type: "move", uci }));
  }

  function newGame() {
    socket?.close();
    gameResult = "";
    gameReason = "";
    status = "setup";
  }
</script>

<main>
  <!-- ── Colour picker ─────────────────────────────────────────── -->
  {#if status === "setup"}
    <div class="setup">
      <h1>vs. {$username}'s Clone</h1>
      <p>Choose your colour</p>
      <div class="color-buttons">
        <button class="color-btn white" onclick={() => chooseColor("white")}>
          <span class="piece">♔</span> Play as White
        </button>
        <button class="color-btn black" onclick={() => chooseColor("black")}>
          <span class="piece">♚</span> Play as Black
        </button>
      </div>
    </div>

  {:else}
    <!-- ── Game view ──────────────────────────────────────────────── -->
    <header>
      <h1>vs. {$username}'s Clone</h1>

      {#if status === "connecting"}
        <p class="status">
          {userColor === "black" ? "Waiting for clone's opening move…" : "Connecting…"}
        </p>
      {:else if status === "game_over"}
        <p class="status result">
          {gameResult === "1-0" && userColor === "white" ? "You won" :
           gameResult === "0-1" && userColor === "black" ? "You won" :
           gameResult === "1/2-1/2" ? "Draw" : "Clone won"}
          — {gameReason}
        </p>
        <div class="actions">
          <button onclick={newGame}>New game</button>
        </div>
      {:else if status === "playing"}
        <p class="status turn">
          {boardLocked ? "Clone is thinking…" : "Your turn"}
        </p>
      {/if}

      {#if errorMsg}
        <p class="error">{errorMsg}</p>
        {#if fatalError}
          <button onclick={newGame}>New game</button>
        {/if}
      {/if}
    </header>

    <div class="board-area">
      <Board
        {fen}
        orientation={userColor}
        {userColor}
        onMove={handleMove}
        locked={boardLocked}
      />
    </div>

    {#if lastStyleScores}
      <section class="scores">
        <h2>Clone's last move — style scores</h2>
        <div class="score-grid">
          <span>Opening affinity</span>
          <meter value={lastStyleScores.opening_affinity} min="0" max="1"></meter>
          <span class="val">{lastStyleScores.opening_affinity.toFixed(2)}</span>

          <span>Aggression match</span>
          <meter value={lastStyleScores.aggression_match} min="0" max="1"></meter>
          <span class="val">{lastStyleScores.aggression_match.toFixed(2)}</span>

          <span>Complexity pref.</span>
          <meter value={lastStyleScores.complexity_preference} min="0" max="1"></meter>
          <span class="val">{lastStyleScores.complexity_preference.toFixed(2)}</span>

          <span>Time accuracy</span>
          <meter value={lastStyleScores.time_adjusted_accuracy} min="0" max="1"></meter>
          <span class="val">{lastStyleScores.time_adjusted_accuracy.toFixed(2)}</span>
        </div>
      </section>
    {/if}
  {/if}
</main>

<style>
  main {
    max-width: 700px;
    margin: 3rem auto;
    font-family: sans-serif;
    padding: 0 1rem;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 1.5rem;
  }

  /* ── Setup screen ── */
  .setup {
    text-align: center;
    margin-top: 4rem;
  }
  .setup h1 { font-size: 2rem; margin-bottom: 0.5rem; }
  .setup p { color: #555; margin-bottom: 1.5rem; }
  .color-buttons { display: flex; gap: 1rem; justify-content: center; }
  .color-btn {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 0.4rem;
    padding: 1.2rem 2rem;
    border: 2px solid #d1d5db;
    border-radius: 10px;
    background: #f9fafb;
    color: #111;
    cursor: pointer;
    font-size: 1rem;
    font-weight: 600;
    transition: border-color 0.15s, background 0.15s;
  }
  .color-btn:hover { border-color: #2563eb; background: #eff6ff; }
  .color-btn.black { background: #1f2937; color: #f9fafb; border-color: #374151; }
  .color-btn.black:hover { border-color: #60a5fa; }
  .piece { font-size: 2.5rem; line-height: 1; }

  /* ── Game view ── */
  header { text-align: center; width: 100%; }
  h1 { font-size: 1.8rem; margin: 0 0 0.4rem; }
  .status { margin: 0.25rem 0; color: #555; }
  .result { font-weight: 600; color: #111; }
  .turn { color: #16a34a; font-weight: 500; }
  .error { color: #dc2626; margin: 0.25rem 0; }
  .actions { margin-top: 0.5rem; }
  button {
    padding: 0.5rem 1.2rem;
    background: #2563eb;
    color: #fff;
    border: none;
    border-radius: 6px;
    cursor: pointer;
    font-size: 1rem;
  }
  .board-area { display: flex; justify-content: center; }

  /* ── Style scores ── */
  .scores { width: 100%; max-width: 480px; }
  h2 { font-size: 1rem; color: #374151; margin-bottom: 0.5rem; }
  .score-grid {
    display: grid;
    grid-template-columns: 1fr auto auto;
    gap: 0.3rem 0.6rem;
    align-items: center;
    font-size: 0.9rem;
  }
  meter { width: 100px; }
  .val { font-variant-numeric: tabular-nums; color: #374151; }
</style>
