/**
 * Where signing in should land, when the trip started somewhere else.
 *
 * A sign-in that interrupted something carries the interrupted address along
 * as `next`, and three places read it back: the guard that put it there, the
 * login page, and the provider URL an SSO sign-in leaves for. They agree on
 * one reading, here, so a path one of them carries is a path the others honour.
 *
 * Somewhere in this app only. The value arrives from a URL, so it is resolved
 * against this origin and kept only if it still points at this origin — which
 * is also what the server's own reading of `next` asks of it.
 */
export const returnPath = (next: string | null | undefined): string | null => {
  if (!next?.startsWith("/")) return null;
  try {
    const resolved = new URL(next, window.location.origin);
    if (resolved.origin !== window.location.origin) return null;
    return `${resolved.pathname}${resolved.search}${resolved.hash}`;
  } catch {
    return null;
  }
};
