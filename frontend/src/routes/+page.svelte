<script lang="ts">
  /**
   * # frontend/src/routes/+page.svelte
   * Home page — username entry with a live loading progress indicator.
   *
   * `$effect` with an interval: Svelte 5 runs effects after mount and re-runs
   * when reactive dependencies change. Returning a cleanup function from the
   * effect ensures the interval is cleared when loading stops or the component
   * unmounts — no memory leaks.
   */
  import { goto } from "$app/navigation";
  import { buildProfile } from "$lib/api";
  import { apiError, loadingProfile, profile, username } from "$lib/stores";

  const LOADING_STEPS = [
    "Fetching games from Lichess…",
    "Parsing PGN data…",
    "Calculating style metrics…",
    "Building your profile…",
  ];

  let inputValue = $state("");
  let localError = $state("");
  let loadingMsg = $state(LOADING_STEPS[0]);

  // Rotate loading messages while fetch is in-flight
  $effect(() => {
    if (!$loadingProfile) return;
    let i = 0;
    const id = setInterval(() => {
      i = (i + 1) % LOADING_STEPS.length;
      loadingMsg = LOADING_STEPS[i];
    }, 2200);
    return () => clearInterval(id);
  });

  async function handleSubmit() {
    const uname = inputValue.trim();
    if (!uname) { localError = "Please enter a Lichess username."; return; }

    localError = "";
    loadingMsg = LOADING_STEPS[0];
    $loadingProfile = true;
    $apiError = null;

    try {
      const result = await buildProfile(uname);
      $username = uname;
      $profile = result;
      goto("/profile");
    } catch (err) {
      localError = err instanceof Error ? err.message : "Unknown error";
    } finally {
      $loadingProfile = false;
    }
  }
</script>

<div class="hero">
  <div class="hero-icon">♟</div>
  <h1>ChessClone</h1>
  <p class="tagline">
    Play against an AI that mimics <em>your</em> Lichess playstyle.
  </p>

  <div class="card form-card">
    <label for="uname">Lichess username</label>
    <form onsubmit={(e) => { e.preventDefault(); handleSubmit(); }}>
      <input
        id="uname"
        type="text"
        placeholder="e.g. DrNykterstein"
        bind:value={inputValue}
        disabled={$loadingProfile}
        autocomplete="off"
        spellcheck="false"
      />
      <button class="btn btn-primary" type="submit" disabled={$loadingProfile}>
        {$loadingProfile ? "Analysing…" : "Build my profile →"}
      </button>
    </form>

    {#if $loadingProfile}
      <div class="loading-row">
        <span class="spinner"></span>
        <span class="loading-msg">{loadingMsg}</span>
      </div>
    {/if}

    {#if localError}
      <p class="error">{localError}</p>
    {/if}
  </div>

  <ul class="features">
    <li><span class="feat-icon">📊</span> Analyses your last 100 rated games</li>
    <li><span class="feat-icon">🎭</span> Builds an aggression, accuracy &amp; time profile</li>
    <li><span class="feat-icon">♟</span> Plays moves that match your style</li>
  </ul>
</div>

<style>
  .hero {
    display: flex;
    flex-direction: column;
    align-items: center;
    text-align: center;
    padding-top: 3rem;
    gap: 1rem;
  }
  .hero-icon { font-size: 3.5rem; line-height: 1; }
  h1 { font-size: 2.6rem; font-weight: 800; letter-spacing: -0.03em; }
  .tagline { color: var(--muted); font-size: 1.05rem; max-width: 360px; }

  .form-card {
    width: 100%;
    max-width: 440px;
    margin-top: 0.5rem;
    text-align: left;
  }
  label { font-size: 0.85rem; font-weight: 600; color: var(--muted); display: block; margin-bottom: 0.5rem; }
  form { display: flex; gap: 0.5rem; }
  input {
    flex: 1;
    padding: 0.6rem 0.9rem;
    font-size: 1rem;
    border: 1.5px solid var(--border);
    border-radius: var(--radius);
    background: var(--bg);
    outline: none;
    transition: border-color 0.15s;
  }
  input:focus { border-color: var(--accent); }
  input:disabled { opacity: 0.6; }

  .loading-row {
    display: flex;
    align-items: center;
    gap: 0.6rem;
    margin-top: 0.8rem;
    font-size: 0.88rem;
    color: var(--muted);
  }
  .spinner {
    width: 14px;
    height: 14px;
    border: 2px solid var(--border);
    border-top-color: var(--accent);
    border-radius: 50%;
    animation: spin 0.7s linear infinite;
    flex-shrink: 0;
  }
  @keyframes spin { to { transform: rotate(360deg); } }
  .loading-msg { transition: opacity 0.3s; }

  .error { color: var(--red); font-size: 0.9rem; margin-top: 0.6rem; }

  .features {
    list-style: none;
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
    margin-top: 1rem;
    font-size: 0.9rem;
    color: var(--muted);
    text-align: left;
  }
  .features li { display: flex; align-items: center; gap: 0.5rem; }
  .feat-icon { font-size: 1rem; }
</style>
