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

export function setItem(key: string, value: string): void {
  if (!isNative()) {
    if (hasLocalStorage) localStorage.setItem(key, value);
    return;
  }
  cache.set(key, value);
  void Preferences.set({ key, value });
}

export function removeItem(key: string): void {
  if (!isNative()) {
    if (hasLocalStorage) localStorage.removeItem(key);
    return;
  }
  cache.delete(key);
  void Preferences.remove({ key });
}
