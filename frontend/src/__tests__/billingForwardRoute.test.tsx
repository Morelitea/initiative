/**
 * The billing link a letter carries, `/c/$communityId/billing?page=…`, through the
 * router the app ships: it has to resolve outside the community layout (a
 * community on hold is not in the community list), and its page has to forward the
 * tab to the portal with a handoff, or say why it did not.
 */
import { createRouter } from "@tanstack/react-router";
import { screen, waitFor } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { routeTree } from "@/routeTree.gen";

import { server } from "./helpers/msw-server";
import { buildRouterContext, renderPage } from "./helpers/render";

const config = vi.hoisted(() => ({ billing: null as { url: string } | null }));
vi.mock("@/hooks/useAppConfig", () => ({
  useAppConfig: () => ({ billing: config.billing, isLoading: false }),
}));

const ROUTE_ID = "/_serverRequired/_authenticated/c/$communityId_/billing";
const HANDOFF = "/api/v1/communities/:communityId/billing/handoff";

const router = createRouter({ routeTree, context: buildRouterContext() });
const route = router.routesById[ROUTE_ID];

const renderForwarder = async (
  options: Omit<Parameters<typeof renderPage>[1], "initialRoute" | "routeParams"> = {}
) => {
  const Page = route.options.component as React.ComponentType & {
    preload?: () => Promise<unknown>;
  };
  // The dynamic import the route is declared with: a moved page or a renamed
  // export fails here rather than at a click.
  await Page.preload?.();
  return renderPage(Page, {
    initialRoute: "/c/$communityId/billing",
    routeParams: { communityId: "7" },
    ...options,
  });
};

let replace: ReturnType<typeof vi.fn>;

beforeEach(() => {
  config.billing = { url: "https://billing.example" };
  replace = vi.fn();
  vi.stubGlobal("location", { ...window.location, replace });
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("the billing forwarder", () => {
  it("is served outside the community layout, landing on manage unless asked to upgrade", () => {
    expect(router.matchRoutes("/c/7/billing", {}).at(-1)?.routeId).toBe(ROUTE_ID);
    const validate = route.options.validateSearch as (s: Record<string, unknown>) => unknown;
    expect(validate({ page: "upgrade" })).toEqual({ page: "upgrade" });
    expect(validate({ page: "elsewhere" })).toEqual({ page: "manage" });
  });

  it("replaces the tab with the portal page, carrying the handoff", async () => {
    const minted = vi.fn();
    server.use(
      http.post(HANDOFF, ({ params }) => {
        minted(params.communityId);
        return HttpResponse.json({ handoff_token: "tok/1", expires_in_seconds: 60 });
      })
    );

    await renderForwarder({ routerSearch: { page: "upgrade" } });

    expect(await screen.findByText("Opening the billing portal…")).toBeInTheDocument();
    await waitFor(() =>
      expect(replace).toHaveBeenCalledWith(
        "https://billing.example/upgrade?community=7&lang=en#handoff=tok%2F1"
      )
    );
    expect(minted).toHaveBeenCalledTimes(1);
    expect(minted).toHaveBeenCalledWith("7");
  });

  it("says why when the server refuses, and stays", async () => {
    server.use(
      http.post(HANDOFF, () =>
        HttpResponse.json({ detail: "COMMUNITY_SUPERADMIN_REQUIRED" }, { status: 403 })
      )
    );

    await renderForwarder();

    expect(
      await screen.findByText("Only a superadmin can change this community's configuration.")
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "← Back to home" })).toHaveAttribute("href", "/");
    expect(replace).not.toHaveBeenCalled();
  });

  it("asks for nothing on a server with no portal, nor in the app", async () => {
    const minted = vi.fn();
    server.use(
      http.post(HANDOFF, () => {
        minted();
        return HttpResponse.json({ handoff_token: "tok", expires_in_seconds: 60 });
      })
    );

    const { unmount } = await renderForwarder({ server: { isNativePlatform: true } });
    expect(await screen.findByText("Not available in the app")).toBeInTheDocument();
    expect(screen.getByText("Plan changes aren't available in the app.")).toBeInTheDocument();
    unmount();

    config.billing = null;
    await renderForwarder();
    expect(await screen.findByText("No billing portal")).toBeInTheDocument();

    expect(minted).not.toHaveBeenCalled();
    expect(replace).not.toHaveBeenCalled();
  });
});
