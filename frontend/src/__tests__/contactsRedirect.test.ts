/**
 * The address My Contacts used to answer on.
 *
 * The page is gone; the address is not. It shipped in a release as a
 * navigation item, which is enough for a bookmark and for a link in somebody's
 * chat, so `/contacts` sends them to My Messages — where everything that page
 * did now happens — rather than to nothing.
 *
 * This is asserted against the route tree the app actually ships, because the
 * only thing that could quietly break it is a change to that tree.
 */
import { createRouter } from "@tanstack/react-router";
import { describe, expect, it } from "vitest";

import { routeTree } from "@/routeTree.gen";

const CONTACTS_ROUTE_ID = "/_serverRequired/_authenticated/contacts";

const router = createRouter({ routeTree });

describe("the retired contacts address", () => {
  it("is still served by the shipped route tree", () => {
    const matches = router.matchRoutes({ pathname: "/contacts", search: {} }, { preload: true });

    expect(String(matches.at(-1)?.routeId)).toBe(CONTACTS_ROUTE_ID);
  });

  it("draws nothing of its own, so it can only redirect", () => {
    const route = router.routesById[CONTACTS_ROUTE_ID];

    expect(route.options.component).toBeUndefined();
    expect(route.options.beforeLoad).toBeTypeOf("function");
  });

  it("sends a stale link to My Messages, replacing itself in history", () => {
    const route = router.routesById[CONTACTS_ROUTE_ID];
    // `beforeLoad` throws the redirect rather than returning it, which is how
    // the router is told to abandon this match.
    let thrown: unknown;
    try {
      (route.options.beforeLoad as () => void)();
    } catch (error) {
      thrown = error;
    }

    // Replaced, not pushed: Back should return where the reader came from
    // rather than to an address that only bounces them forward again.
    expect(thrown).toMatchObject({ options: { to: "/messages", replace: true } });
  });
});
