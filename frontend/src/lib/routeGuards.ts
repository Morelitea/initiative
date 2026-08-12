import { redirect } from "@tanstack/react-router";

import type { RouterContext } from "@/router";

/**
 * beforeLoad for legacy non-guild paths: forward to the active guild's copy
 * of the route (search params included when the route has them), or home when
 * no guild is active.
 */
export function redirectToActiveGuild(to: string) {
  return ({
    context,
    search,
  }: {
    context: RouterContext;
    search?: Record<string, unknown>;
  }): void => {
    const guildId = context.guilds?.activeGuildId;
    if (guildId) {
      throw redirect({
        to,
        params: { guildId: String(guildId) },
        // A runtime `to` makes the router type `search` as the union of every
        // route's schema; the forwarded object is already a valid subset.
        search: (search ?? {}) as never,
      });
    }
    throw redirect({ to: "/" });
  };
}

/**
 * Keeps the layout route guards (`_serverRequired`, `_authenticated`) authoritative.
 *
 * Those guards live in `beforeLoad` and throw `redirect()`, which the router
 * resolves at the navigation layer. But `beforeLoad` only runs when the router
 * loads: at boot, auth and server state are still `loading`, so the guards pass
 * and the layouts mount. When that state settles moments later there is nothing
 * to make the router look again — which is why the layouts used to redirect by
 * rendering `<Navigate>` instead, a fallback that re-navigates on every render
 * and only terminates because the layout unmounts.
 *
 * The signature below captures exactly what those guards branch on. When it
 * changes, `useRouteGuardSync` invalidates the router so `beforeLoad` re-runs
 * and the redirect is decided in one place, at the navigation layer.
 */

export interface GuardAuthState {
  loading: boolean;
  user: { id: number } | null;
}

export interface GuardServerState {
  loading: boolean;
  isNativePlatform: boolean;
  isServerConfigured: boolean;
}

/**
 * Serializes the guard-relevant slice of the router context.
 *
 * Deliberately narrow: only the fields the guards read are included, so
 * unrelated context churn (a refreshed user object, a guild list reorder)
 * doesn't trigger a router-wide re-evaluation. While a slice is still
 * `loading` its concrete values are omitted — the guards don't act on them
 * yet, and including them would invalidate for a decision nobody makes.
 */
export function routeGuardSignature(
  auth: GuardAuthState | undefined,
  server: GuardServerState | undefined
): string {
  const authPart = !auth
    ? "auth:absent"
    : auth.loading
      ? "auth:loading"
      : `auth:${auth.user?.id ?? "anonymous"}`;
  const serverPart = !server
    ? "server:absent"
    : server.loading
      ? "server:loading"
      : `server:${server.isNativePlatform ? "native" : "web"}:${
          server.isServerConfigured ? "configured" : "unconfigured"
        }`;
  return `${authPart}|${serverPart}`;
}
