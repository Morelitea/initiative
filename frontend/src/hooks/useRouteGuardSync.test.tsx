import { renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { GuardAuthState, GuardServerState } from "@/lib/routeGuards";

import { useRouteGuardSync } from "./useRouteGuardSync";

const web: GuardServerState = {
  loading: false,
  isNativePlatform: false,
  isServerConfigured: true,
};

const renderSync = (auth: GuardAuthState | undefined, server = web) => {
  const router = { invalidate: vi.fn() };
  const view = renderHook(
    ({ auth: a, server: s }: { auth: GuardAuthState | undefined; server: GuardServerState }) =>
      useRouteGuardSync(router, a, s),
    { initialProps: { auth, server } }
  );
  return { router, view };
};

describe("useRouteGuardSync", () => {
  it("does not invalidate on mount — the initial load already ran the guards", () => {
    const { router } = renderSync({ loading: true, user: null });
    expect(router.invalidate).not.toHaveBeenCalled();
  });

  it("invalidates when auth settles to signed out", () => {
    const { router, view } = renderSync({ loading: true, user: null });
    view.rerender({ auth: { loading: false, user: null }, server: web });
    expect(router.invalidate).toHaveBeenCalledTimes(1);
  });

  it("invalidates when auth settles to signed in", () => {
    const { router, view } = renderSync({ loading: true, user: null });
    view.rerender({ auth: { loading: false, user: { id: 3 } }, server: web });
    expect(router.invalidate).toHaveBeenCalledTimes(1);
  });

  it("invalidates on sign out", () => {
    const { router, view } = renderSync({ loading: false, user: { id: 3 } });
    view.rerender({ auth: { loading: false, user: null }, server: web });
    expect(router.invalidate).toHaveBeenCalledTimes(1);
  });

  it("stays quiet when an equivalent user object is swapped in", () => {
    const { router, view } = renderSync({ loading: false, user: { id: 3 } });
    view.rerender({ auth: { loading: false, user: { id: 3 } }, server: { ...web } });
    view.rerender({ auth: { loading: false, user: { id: 3 } }, server: { ...web } });
    expect(router.invalidate).not.toHaveBeenCalled();
  });

  it("invalidates once per transition, not once per render", () => {
    const { router, view } = renderSync({ loading: true, user: null });
    const settled = { loading: false, user: null };
    view.rerender({ auth: settled, server: web });
    view.rerender({ auth: { ...settled }, server: web });
    view.rerender({ auth: { ...settled }, server: web });
    expect(router.invalidate).toHaveBeenCalledTimes(1);
  });

  it("invalidates when a native install gains a configured server", () => {
    const auth = { loading: false, user: null };
    const { router, view } = renderSync(auth, {
      loading: false,
      isNativePlatform: true,
      isServerConfigured: false,
    });
    view.rerender({
      auth,
      server: { loading: false, isNativePlatform: true, isServerConfigured: true },
    });
    expect(router.invalidate).toHaveBeenCalledTimes(1);
  });
});
