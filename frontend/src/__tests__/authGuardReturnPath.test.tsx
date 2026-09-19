/**
 * What a signed-out visit to a page behind sign-in carries with it.
 *
 * The whole point of the trip is the return: the app sends a phone to a
 * browser to add a passkey, that browser is asked to sign in first, and the
 * page it was sent to is where it should land. That carry lives in the
 * generated route tree's guard, so it is read here through the real tree —
 * a hand-built route would prove the redirect and not the registration.
 */
import { QueryClient } from "@tanstack/react-query";
import { createMemoryHistory, createRouter, isRedirect } from "@tanstack/react-router";
import { describe, expect, it } from "vitest";

import type { RouterContext } from "@/router";
import { routeTree } from "@/routeTree.gen";

/** A router over the shipped tree with nobody signed in, on the web. */
const signedOut = (pathname: string) =>
  createRouter({
    routeTree,
    history: createMemoryHistory({ initialEntries: [pathname] }),
    context: {
      queryClient: new QueryClient(),
      auth: { user: null, loading: false },
      guilds: undefined,
      server: { loading: false, isNativePlatform: false, isServerConfigured: true },
    } as unknown as RouterContext,
  });

/** Where the guard sent them, and with what. */
const landing = async (pathname: string) => {
  const router = signedOut(pathname);
  try {
    await router.load();
  } catch (error) {
    // Some router versions hand the redirect back rather than following it.
    if (!isRedirect(error)) throw error;
    return {
      to: String((error as { to?: string }).to ?? ""),
      search: ((error as { search?: Record<string, unknown> }).search ?? {}) as Record<
        string,
        unknown
      >,
    };
  }
  return {
    to: router.state.location.pathname,
    search: router.state.location.search as Record<string, unknown>,
  };
};

describe("a page behind sign-in", () => {
  it("sends a signed-out visitor to the front door holding the page they asked for", async () => {
    const { to, search } = await landing("/profile/security");

    expect(to).toBe("/welcome");
    expect(search.next).toBe("/profile/security");
  });

  it("asks nobody to return to the page they would have landed on anyway", async () => {
    const { to, search } = await landing("/");

    expect(to).toBe("/welcome");
    expect(search.next).toBeUndefined();
  });
});
