<script lang="ts">
  import favicon from '$lib/assets/favicon.svg';
  import '../app.css';
  import "chessground/assets/chessground.base.css";
  import "chessground/assets/chessground.brown.css";
  import "chessground/assets/chessground.cburnett.css";
  import { page } from '$app/stores';
  import { profile, username } from '$lib/stores';

  let { children } = $props();

  // Derive a breadcrumb label from the current path
  const labels: Record<string, string> = {
    '/': 'Home',
    '/profile': 'Profile',
    '/play': 'Play',
  };
</script>

<svelte:head>
  <link rel="icon" href={favicon} />
  <title>ChessClone</title>
</svelte:head>

<nav>
  <a href="/" class="logo">♟ ChessClone</a>

  <div class="breadcrumb">
    {#if $page.url.pathname === '/profile' || $page.url.pathname === '/play'}
      <a href="/">Home</a>
      <span class="sep">›</span>
    {/if}
    {#if $page.url.pathname === '/play'}
      <a href="/profile">Profile</a>
      <span class="sep">›</span>
    {/if}
    <span class="current">{labels[$page.url.pathname] ?? ''}</span>
  </div>

  <div class="nav-right">
    {#if $profile}
      <a href="/profile" class="username-chip">{$username}</a>
    {/if}
  </div>
</nav>

<div class="page-wrap">
  {@render children()}
</div>

<style>
  nav {
    display: flex;
    align-items: center;
    gap: 1rem;
    padding: 0 1.5rem;
    height: 52px;
    background: var(--surface);
    border-bottom: 1px solid var(--border);
    position: sticky;
    top: 0;
    z-index: 10;
  }
  .logo {
    font-weight: 700;
    font-size: 1.05rem;
    text-decoration: none;
    color: var(--fg);
    white-space: nowrap;
  }
  .breadcrumb {
    display: flex;
    align-items: center;
    gap: 0.35rem;
    font-size: 0.85rem;
    color: var(--muted);
    flex: 1;
  }
  .breadcrumb a { color: var(--muted); text-decoration: none; }
  .breadcrumb a:hover { color: var(--accent); }
  .sep { opacity: 0.4; }
  .current { color: var(--fg); font-weight: 500; }
  .nav-right { margin-left: auto; }
  .username-chip {
    font-size: 0.85rem;
    font-weight: 600;
    color: var(--accent);
    text-decoration: none;
    padding: 0.2rem 0.7rem;
    border: 1.5px solid var(--accent);
    border-radius: 999px;
  }
  .username-chip:hover { background: #eff6ff; }
  .page-wrap {
    max-width: 800px;
    margin: 0 auto;
    padding: 2.5rem 1rem 4rem;
  }
</style>
