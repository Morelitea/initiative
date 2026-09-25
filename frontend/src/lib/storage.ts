import { Capacitor } from "@capacitor/core";
import { Preferences } from "@capacitor/preferences";

const isNative = () => Capacitor.isNativePlatform();
const hasLocalStorage = typeof localStorage !== "undefined";

/**
 * In-memory cache used on native platforms. Hydrated once at startup from
 * Capacitor Preferences so that all subsequent reads are synchronous.
 */
const cache = new Map<string, string>();

/**
 * Call once before React renders. On web this is a no-op (resolves instantly).
 * On native it loads every persisted key into the in-memory cache so that
 * getItem() can remain synchronous.
 */
export async function initStorage(): Promise<void> {
  if (!isNative()) {
    return;
  }
  const { keys } = await Preferences.keys();
  if (!Array.isArray(keys)) {
    return;
  }
  const entries = await Promise.all(
    keys.map(async (key) => {
      const { value } = await Preferences.get({ key });
      return [key, value] as const;
    })
  );
  for (const [key, value] of entries) {
    if (value !== null) {
      cache.set(key, value);
    }
  }
}

export function getItem(key: string): string | null {
  if (!isNative()) {
    return hasLocalStorage ? localStorage.getItem(key) : null;
  }
  return cache.get(key) ?? null;
}

/**
 * Reads see the value at once. On native the durable write finishes later;
 * await the result where the app may be closed before it does.
 */
export function setItem(key: string, value: string): Promise<void> {
  if (!isNative()) {
    if (hasLocalStorage) localStorage.setItem(key, value);
    return Promise.resolve();
  }
  cache.set(key, value);
  return Preferences.set({ key, value });
}

/**
 * Mirror a value into the WebView's own localStorage as well, for the one
 * reader that runs before any of this module exists: the pre-paint script in
 * index.html. On web, `setItem` already lands there. On native the durable
 * copy is in Preferences and this is only a hint — the OS may clear it, and
 * the script falls back to the system theme when it is gone.
 */
export function setFirstPaintHint(key: string, value: string): void {
  if (!isNative() || !hasLocalStorage) return;
  try {
    localStorage.setItem(key, value);
  } catch {
    // A hint only: the first frame falls back to the system theme.
  }
}

export function removeItem(key: string): Promise<void> {
  if (!isNative()) {
    if (hasLocalStorage) localStorage.removeItem(key);
    return Promise.resolve();
  }
  cache.delete(key);
  return Preferences.remove({ key });
}

/** Enumerate every stored key. */
export function listKeys(): string[] {
  if (!isNative()) {
    if (!hasLocalStorage) return [];
    return Object.keys(localStorage);
  }
  return Array.from(cache.keys());
}
