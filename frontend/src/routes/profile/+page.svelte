<script lang="ts">
  /**
   * # frontend/src/routes/profile/+page.svelte
   * Style dashboard — stat cards, opening repertoire, and a play CTA.
   */
  import { goto } from "$app/navigation";
  import { profile, username } from "$lib/stores";
  import { onMount } from "svelte";

  onMount(() => { if (!$profile) goto("/"); });

  // ---- helpers ----

  /** Map a 0–1 value to a CSS color: green (low) → amber → red (high). */
  function riskColor(v: number): string {
    if (v < 0.33) return "var(--green)";
    if (v < 0.66) return "var(--amber)";
    return "var(--red)";
  }

  /** Map 0–1 aggression to a label. */
  function aggressionLabel(v: number): string {
    if (v < 0.25) return "Solid / Positional";
    if (v < 0.5)  return "Balanced";
    if (v < 0.75) return "Active";
    return "Attacking";
  }

  /** Format a UCI string as a readable move: "e2e4" → "e4", "g1f3" → "Nf3". */
  const PIECE_GLYPHS: Record<string, string> = {
    n: "N", b: "B", r: "R", q: "Q", k: "K",
  };
  function formatUci(uci: string): string {
    if (!uci || uci.length < 4) return uci;
    const [, , toFile, toRank] = uci;
    const fromFile = uci[0];
    const piece = PIECE_GLYPHS[fromFile] ?? ""; // only works for knights/bishops etc.
    // Detect piece moves: origin square belongs to a non-pawn if glyph exists.
    // Simple heuristic: if from-file differs from to-file without capture context,
    // we try to detect it from common starting squares.
    const knightSquares = new Set(["g1","b1","g8","b8"]);
    const bishopSquares = new Set(["c1","f1","c8","f8"]);
    const fromSq = uci.slice(0, 2);
    if (knightSquares.has(fromSq)) return `N${toFile}${toRank}`;
    if (bishopSquares.has(fromSq)) return `B${toFile}${toRank}`;
    return `${toFile}${toRank}`; // pawn move
  }

  // Flatten black responses into the most common vs e4 / vs d4 / vs other
  function topResponses(responses: Record<string, Record<string, number>>, against: string): [string, number][] {
    const r = responses[against] ?? {};
    return Object.entries(r).sort((a, b) => b[1] - a[1]).slice(0, 4);
  }
</script>

{#if $profile}
  {@const p = $profile}

  <!-- ── Header ────────────────────────────────────────────── -->
  <div class="page-header">
    <div>
      <h1>{$username}'s Style Profile</h1>
      <p class="subtitle">Based on {p.games_analyzed} analysed games</p>
    </div>
    <a href="/play" class="btn btn-green">Play against clone →</a>
  </div>

  <!-- ── Stat cards grid ───────────────────────────────────── -->
  <div class="stat-grid">

    <!-- Aggression -->
    <div class="card stat-card">
      <div class="card-label">Aggression</div>
      <div class="card-value" style="color: {riskColor(p.aggression_index)}">
        {(p.aggression_index * 100).toFixed(0)}%
      </div>
      <div class="bar-track">
        <div class="bar-fill" style="width:{p.aggression_index*100}%; background:{riskColor(p.aggression_index)}"></div>
      </div>
      <div class="card-sub">{aggressionLabel(p.aggression_index)}</div>
    </div>

    <!-- Avg CPL -->
    <div class="card stat-card">
      <div class="card-label">Avg centipawn loss</div>
      <div class="card-value" style="color: {riskColor(Math.min(1, p.accuracy.avg_centipawn_loss / 150))}">
        {p.accuracy.avg_centipawn_loss.toFixed(0)}
      </div>
      <div class="card-sub">
        {p.accuracy.avg_centipawn_loss < 30 ? "Excellent" :
         p.accuracy.avg_centipawn_loss < 60 ? "Good" :
         p.accuracy.avg_centipawn_loss < 100 ? "Average" : "Needs work"}
      </div>
    </div>

    <!-- Blunders -->
    <div class="card stat-card">
      <div class="card-label">Blunders / game</div>
      <div class="card-value" style="color: {riskColor(Math.min(1, p.accuracy.blunder_rate / 3))}">
        {p.accuracy.blunder_rate.toFixed(2)}
      </div>
      <div class="card-sub">Mistakes: {p.accuracy.mistake_rate.toFixed(2)}/game</div>
    </div>

    <!-- Time management -->
    <div class="card stat-card">
      <div class="card-label">Avg move time</div>
      <div class="card-value">
        {(p.time_signature.avg_move_time_ms / 1000).toFixed(1)}s
      </div>
      <div class="card-sub">
        {#if p.time_signature.time_pressure_accuracy_drop > 0}
          +{p.time_signature.time_pressure_accuracy_drop.toFixed(0)} CPL under pressure
        {:else}
          Steady under pressure
        {/if}
      </div>
    </div>

    <!-- Endgame simplification -->
    <div class="card stat-card">
      <div class="card-label">Endgame simplification</div>
      <div class="card-value">{(p.endgame_simplification_rate * 100).toFixed(0)}%</div>
      <div class="bar-track">
        <div class="bar-fill" style="width:{p.endgame_simplification_rate*100}%; background:var(--accent)"></div>
      </div>
      <div class="card-sub">
        {p.endgame_simplification_rate > 0.6 ? "Likes trading pieces" :
         p.endgame_simplification_rate > 0.3 ? "Selective trader" : "Keeps pieces on board"}
      </div>
    </div>

    <!-- Opening deviation depth -->
    <div class="card stat-card">
      <div class="card-label">Opening book depth</div>
      <div class="card-value">{p.opening_dna.avg_deviation_depth.toFixed(1)} ply</div>
      <div class="card-sub">
        {p.opening_dna.avg_deviation_depth > 12 ? "Deep preparation" :
         p.opening_dna.avg_deviation_depth > 6  ? "Moderate preparation" : "Plays freely early"}
      </div>
    </div>

  </div>

  <!-- ── Opening DNA ───────────────────────────────────────── -->
  <div class="card opening-card">
    <h2>Opening DNA</h2>

    <div class="opening-cols">

      <!-- As White -->
      {#if Object.keys(p.opening_dna.white_first_moves).length > 0}
        <div class="opening-col">
          <h3>As White — first move</h3>
          <ul class="move-list">
            {#each Object.entries(p.opening_dna.white_first_moves) as [uci, freq]}
              <li>
                <span class="move-chip">{formatUci(uci)}</span>
                <div class="move-bar-track">
                  <div class="move-bar-fill" style="width:{freq*100}%"></div>
                </div>
                <span class="move-pct">{(freq*100).toFixed(0)}%</span>
              </li>
            {/each}
          </ul>
        </div>
      {/if}

      <!-- As Black vs e4 -->
      {#if topResponses(p.opening_dna.black_responses, "e2e4").length > 0}
        <div class="opening-col">
          <h3>As Black vs 1.e4</h3>
          <ul class="move-list">
            {#each topResponses(p.opening_dna.black_responses, "e2e4") as [uci, freq]}
              <li>
                <span class="move-chip">{formatUci(uci)}</span>
                <div class="move-bar-track">
                  <div class="move-bar-fill" style="width:{freq*100}%"></div>
                </div>
                <span class="move-pct">{(freq*100).toFixed(0)}%</span>
              </li>
            {/each}
          </ul>
        </div>
      {/if}

      <!-- As Black vs d4 -->
      {#if topResponses(p.opening_dna.black_responses, "d2d4").length > 0}
        <div class="opening-col">
          <h3>As Black vs 1.d4</h3>
          <ul class="move-list">
            {#each topResponses(p.opening_dna.black_responses, "d2d4") as [uci, freq]}
              <li>
                <span class="move-chip">{formatUci(uci)}</span>
                <div class="move-bar-track">
                  <div class="move-bar-fill" style="width:{freq*100}%"></div>
                </div>
                <span class="move-pct">{(freq*100).toFixed(0)}%</span>
              </li>
            {/each}
          </ul>
        </div>
      {/if}

      <!-- Top ECOs -->
      <div class="opening-col">
        <h3>Top ECO codes</h3>
        <ul class="eco-list">
          {#each Object.entries(p.opening_dna.eco_frequency).slice(0, 6) as [eco, freq]}
            <li>
              <span class="eco-chip">{eco}</span>
              <div class="move-bar-track">
                <div class="move-bar-fill" style="width:{freq*100}%"></div>
              </div>
              <span class="move-pct">{(freq*100).toFixed(0)}%</span>
            </li>
          {/each}
        </ul>
      </div>

    </div>
  </div>

  <!-- ── Play CTA ───────────────────────────────────────────── -->
  <div class="cta-row">
    <a href="/play" class="btn btn-green">Play against {$username}'s clone →</a>
    <button class="btn btn-ghost" onclick={() => goto("/")}>← Different player</button>
  </div>
{/if}

<style>
  .page-header {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 1rem;
    flex-wrap: wrap;
    margin-bottom: 1.5rem;
  }
  h1 { font-size: 1.75rem; font-weight: 700; }
  .subtitle { color: var(--muted); font-size: 0.9rem; margin-top: 0.2rem; }

  /* ── Stat grid ── */
  .stat-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
    gap: 1rem;
    margin-bottom: 1.5rem;
  }
  .stat-card { display: flex; flex-direction: column; gap: 0.3rem; }
  .card-label { font-size: 0.78rem; font-weight: 600; color: var(--muted); text-transform: uppercase; letter-spacing: 0.04em; }
  .card-value { font-size: 2rem; font-weight: 700; line-height: 1.1; }
  .card-sub { font-size: 0.82rem; color: var(--muted); }
  .bar-track { height: 6px; background: var(--border); border-radius: 999px; overflow: hidden; }
  .bar-fill { height: 100%; border-radius: 999px; transition: width 0.5s ease; }

  /* ── Opening DNA card ── */
  .opening-card { margin-bottom: 1.5rem; }
  .opening-card h2 { font-size: 1rem; font-weight: 700; margin-bottom: 1rem; }
  .opening-cols {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
    gap: 1.5rem;
  }
  .opening-col h3 { font-size: 0.8rem; font-weight: 600; color: var(--muted); text-transform: uppercase; letter-spacing: 0.04em; margin-bottom: 0.6rem; }
  .move-list, .eco-list { list-style: none; display: flex; flex-direction: column; gap: 0.45rem; }
  .move-list li, .eco-list li { display: grid; grid-template-columns: 44px 1fr 32px; align-items: center; gap: 0.4rem; font-size: 0.88rem; }
  .move-chip {
    font-family: monospace;
    font-weight: 700;
    font-size: 0.85rem;
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: 4px;
    padding: 0.1rem 0.35rem;
    text-align: center;
  }
  .eco-chip {
    font-family: monospace;
    font-weight: 700;
    font-size: 0.8rem;
    color: var(--accent);
    background: #eff6ff;
    border-radius: 4px;
    padding: 0.1rem 0.35rem;
    text-align: center;
  }
  .move-bar-track { height: 5px; background: var(--border); border-radius: 999px; overflow: hidden; }
  .move-bar-fill { height: 100%; background: var(--accent); border-radius: 999px; }
  .move-pct { font-size: 0.78rem; color: var(--muted); text-align: right; }

  /* ── CTA row ── */
  .cta-row { display: flex; gap: 0.75rem; flex-wrap: wrap; }
</style>
