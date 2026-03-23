/**
 * # frontend/src/lib/stores.ts
 *
 * Svelte STORES — shared reactive state across routes.
 *
 * What is a Svelte store?
 *   A store is an object with a `subscribe` method. Any component that
 *   subscribes (via the `$` prefix in templates) automatically re-renders
 *   when the value changes. `writable` stores can also be set/updated from
 *   anywhere, making them ideal for global state like "the current profile".
 */

import { writable } from "svelte/store";
import type { StyleProfile } from "./api";

/** The currently loaded StyleProfile, or null if none loaded yet. */
export const profile = writable<StyleProfile | null>(null);

/** Username entered by the user on the home page. */
export const username = writable<string>("");

/** Whether a profile fetch is in flight. */
export const loadingProfile = writable<boolean>(false);

/** Last error message from an API call, or null. */
export const apiError = writable<string | null>(null);
