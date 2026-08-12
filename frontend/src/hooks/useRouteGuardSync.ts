import { useEffect, useRef } from "react";

import { type GuardAuthState, type GuardServerState, routeGuardSignature } from "@/lib/routeGuards";

/** The slice of the router this hook needs — narrow so tests can pass a stub. */
interface InvalidatableRouter {
  invalidate: () => unknown;
}

/**
 * Re-runs the layout `beforeLoad` guards whenever the state they read settles
 * or changes (boot finishing, sign-in, sign-out, a native server being
 * configured).
 *
 * `RouterProvider` merges the fresh context into the router during render, but
 * merging alone doesn't re-evaluate anything; `invalidate()` marks the current
 * matches stale and reloads them, which is what puts `beforeLoad` — and its
 * `redirect()` — back in charge. Mount is skipped: the initial load already ran
 * with that context.
 */
export function useRouteGuardSync(
  router: InvalidatableRouter,
  auth: GuardAuthState | undefined,
  server: GuardServerState | undefined
): void {
  const signature = routeGuardSignature(auth, server);
  const lastSignature = useRef(signature);

  useEffect(() => {
    if (lastSignature.current === signature) return;
    lastSignature.current = signature;
    void router.invalidate();
  }, [router, signature]);
}
