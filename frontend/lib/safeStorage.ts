/**
 * Storage access that survives browsers which block it.
 *
 * Brave (with Shields / "block all cookies"), Safari private mode and some
 * Android configurations throw SecurityError on mere access to localStorage.
 * An unguarded read inside a React effect unmounts the whole tree, so every
 * access goes through these helpers.
 */

export function storageGet(key: string): string | null {
  try {
    if (typeof window === "undefined") return null;
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

export function storageSet(key: string, value: string): void {
  try {
    if (typeof window === "undefined") return;
    window.localStorage.setItem(key, value);
  } catch {
    // Storage unavailable or full; the in-memory state still works.
  }
}
