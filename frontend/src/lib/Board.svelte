<script lang="ts">
  /**
   * # frontend/src/lib/Board.svelte
   * Interactive chessboard powered by chessground (the Lichess board library).
   *
   * What is `$effect`? (Svelte 5 rune)
   *   Like `$:` reactive declarations but runs *after* the DOM updates.
   *   Use it for side effects that need access to the DOM — perfect here
   *   because chessground needs a real HTMLElement to mount into.
   *   It re-runs automatically whenever any reactive value it reads changes.
   *
   * What is `$props`? (Svelte 5 rune)
   *   Replaces `export let foo` for declaring component props. The object
   *   destructured from `$props()` is reactive — when the parent updates
   *   a prop, the child sees the new value and effects re-run.
   */

  import { Chessground } from "chessground";
  import type { Api } from "chessground/api";
  import type { Key } from "chessground/types";
  import { Chess } from "chess.js";
  import { onDestroy } from "svelte";

  // --- Props ---
  interface Props {
    fen: string;
    orientation?: "white" | "black";
    userColor?: "white" | "black";
    /** Called with UCI string (e.g. "e2e4", "e7e8q") after user drags a piece. */
    onMove: (uci: string) => void;
    /** When true, board is locked (waiting for clone's reply). */
    locked?: boolean;
  }

  let {
    fen,
    orientation = "white",
    userColor = "white",
    onMove,
    locked = false,
  }: Props = $props();

  // --- Internal state ---
  let boardEl: HTMLElement;
  let cg: Api | null = null;
  let chess = new Chess();
  let lastSetFen = "";

  /**
   * Compute legal destinations for chessground.
   * chessground wants Map<from-square, to-square[]> using algebraic keys ("e2").
   * chess.js gives us the same format via moves({ verbose: true }).
   */
  function getLegalDests(): Map<Key, Key[]> {
    const dests = new Map<Key, Key[]>();
    for (const move of chess.moves({ verbose: true })) {
      const existing = dests.get(move.from as Key) ?? [];
      existing.push(move.to as Key);
      dests.set(move.from as Key, existing);
    }
    return dests;
  }

  function isUserTurn(): boolean {
    return (chess.turn() === "w") === (userColor === "white");
  }

  function movableDests(): Map<Key, Key[]> {
    if (locked || !isUserTurn()) return new Map();
    return getLegalDests();
  }

  /**
   * $effect: runs after mount, then re-runs whenever `fen` or `locked` change.
   * First run: initialises chessground in the DOM element.
   * Subsequent runs: syncs the board position and move availability.
   *
   * Gotcha: chessground.set() does a *diff* — only changed keys are updated.
   * Always pass `fen` explicitly so it re-renders the pieces.
   */
  $effect(() => {
    chess.load(fen);
    const turnColor = chess.turn() === "w" ? "white" : "black";
    const dests = movableDests();

    if (!cg) {
      // First run — mount chessground
      cg = Chessground(boardEl, {
        fen,
        orientation,
        turnColor,
        movable: {
          color: userColor,
          dests,
          free: false,
          showDests: true,
        },
        draggable: { enabled: true },
        selectable: { enabled: true },
        animation: { enabled: true, duration: 200 },
        highlight: { lastMove: true, check: true },
        events: {
          move(from: Key, to: Key) {
            // Detect pawn promotion (auto-queen for now; promotion UI is future work)
            const isPromotion = chess
              .moves({ verbose: true })
              .some((m) => m.from === from && m.to === to && m.promotion);

            onMove(from + to + (isPromotion ? "q" : ""));

            // Lock board immediately — unlock happens when parent updates `locked`
            cg!.set({ movable: { dests: new Map() } });
          },
        },
      });
      lastSetFen = fen;
    } else {
      // Only push fen to chessground when it actually changed (server replied).
      // Skipping fen update on locked-only changes prevents the piece snapping
      // back to its origin square while we wait for the clone's response.
      const update: Parameters<typeof cg.set>[0] = {
        turnColor,
        movable: { color: userColor, dests },
      };
      if (fen !== lastSetFen) {
        update.fen = fen;
        lastSetFen = fen;
      }
      cg.set(update);
    }
  });

  onDestroy(() => cg?.destroy());
</script>

<!-- chessground renders into this div; size is driven by CSS -->
<div class="cg-wrap" bind:this={boardEl}></div>

<style>
  /*
   * chessground needs a sized container. We set a fixed square here;
   * the board will fill it. Override in the parent if you want a different size.
   */
  .cg-wrap {
    width: min(480px, 90vw);
    height: min(480px, 90vw);
    display: block;
  }
</style>
