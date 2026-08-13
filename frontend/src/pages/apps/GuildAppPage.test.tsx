/**
 * Which token reaches which frame.
 *
 * A handoff names one surface and is spent on first use, so the page re-mints
 * when a reloading embed asks again. That re-mint is asynchronous, and the tabs
 * of one app all share an origin — so if the reader switches surfaces while it
 * is in flight, the origin check cannot tell the arriving token from a correct
 * one. The delivery has to be dropped instead.
 */

import { screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderPage } from "@/__tests__/helpers/render";

const mint = vi.fn();

vi.mock("@/api/generated/apps/apps", () => ({
  createGuildAppHandoffApiV1GGuildIdAppsAppIdHandoffSurfaceIdPost: (
    _guildId: number,
    _appId: number,
    surfaceId: string
  ) => mint(surfaceId, { scope: "guild" }),
  createInitiativeAppHandoffApiV1GGuildIdInitiativesInitiativeIdAppsAppIdHandoffSurfaceIdPost: (
    _guildId: number,
    initiativeId: number,
    _appId: number,
    surfaceId: string
  ) => mint(surfaceId, { scope: "initiative", initiativeId }),
}));

const detail = {
  id: 1,
  name: "Automations",
  enabled: true,
  available: true,
  definition: {
    embeds: [
      { id: "one", path: "/embed/one", name: { en: "One" } },
      { id: "two", path: "/embed/two", name: { en: "Two" } },
      {
        id: "inside",
        path: "/embed/inside",
        name: { en: "Inside" },
        scopes: ["initiative"],
        visibility: "initiative_manager",
      },
    ],
  },
};

/** A guild admin, who clears every rung wherever they are looking. */
const ADMIN = { isGuildAdmin: true };

vi.mock("@/hooks/useGuildAppDetail", () => ({
  useGuildAppDetail: () => ({ data: detail, isLoading: false }),
}));

vi.mock("@/hooks/useActiveGuildId", () => ({ useActiveGuildId: () => 3 }));

const handoff = (surfaceId: string) => ({
  handoff_token: `token-for-${surfaceId}`,
  expires_in_seconds: 60,
  embed_url: `https://app.example.com/embed/${surfaceId}`,
  allowed_origins: ["https://app.example.com"],
  audience: "initiative-app:acme.demo",
  surface_id: surfaceId,
});

/** Every token this page handed to a frame, ignoring the locale nudges. */
const delivered = () =>
  postSpy.mock.calls
    .map(([message]) => message as { type: string; handoff_token?: string })
    .filter((message) => message.type === "initiative-app:handoff")
    .map((message) => message.handoff_token);

let postSpy: ReturnType<typeof vi.fn>;

beforeEach(() => {
  mint.mockReset();
  postSpy = vi.fn();
  // Every iframe in the page reports the same window, which is the worst case:
  // nothing about the target distinguishes one surface's frame from another's.
  Object.defineProperty(HTMLIFrameElement.prototype, "contentWindow", {
    configurable: true,
    get: () => ({ postMessage: postSpy }),
  });
});

const ready = () =>
  window.dispatchEvent(
    new MessageEvent("message", {
      origin: "https://app.example.com",
      data: { type: "initiative-app:ready" },
    })
  );

/**
 * Announce until the page answers.
 *
 * `ready` is a one-shot with no retry: the page only listens once it holds a
 * token for the mounted frame, and an announcement that lands before then is
 * gone for good. A real embed cannot arrive early — it loads from the src the
 * token produced — but a test dispatching by hand can, since the mounted frame
 * and the listener that serves it settle in that order and a loaded machine can
 * leave a gap between them. Delivery is synchronous inside the listener, so the
 * announcement that lands is the only one that delivers.
 */
const announceReady = () =>
  waitFor(
    () => {
      if (delivered().length === 0) ready();
      expect(delivered()).toEqual(["token-for-one"]);
    },
    { timeout: 5000 }
  );

describe("GuildAppPage", () => {
  it("hands the first surface's token to the frame that asked", async () => {
    mint.mockImplementation((surfaceId: string) => Promise.resolve(handoff(surfaceId)));
    const { GuildAppPage } = await import("./GuildAppPage");
    renderPage(() => <GuildAppPage appId={1} viewer={ADMIN} />);

    await screen.findByTitle("Automations");
    await announceReady();
  });

  it("drops a re-mint that resolves after the surface changed", async () => {
    // First surface mints immediately; the re-mint it triggers is held open so
    // the tab can change underneath it.
    let releaseStale: (value: unknown) => void = () => {};
    mint
      .mockImplementationOnce((surfaceId: string) => Promise.resolve(handoff(surfaceId)))
      .mockImplementationOnce(() => new Promise((resolve) => (releaseStale = resolve)))
      .mockImplementation((surfaceId: string) => Promise.resolve(handoff(surfaceId)));

    const { GuildAppPage } = await import("./GuildAppPage");
    renderPage(() => <GuildAppPage appId={1} viewer={ADMIN} />);

    await screen.findByTitle("Automations");
    await announceReady(); // spends the first token

    ready(); // the embed reloaded: starts the re-mint that will go stale
    (await screen.findByText("Two")).click();
    await waitFor(() => expect(mint).toHaveBeenCalledWith("two", expect.anything()));

    // The held re-mint now answers, for a surface nobody is looking at.
    releaseStale(handoff("one"));
    await new Promise((resolve) => setTimeout(resolve, 0));

    // Unchanged: the stale token was dropped rather than handed to the frame
    // now showing the other surface. Surface two has minted but not been asked,
    // so nothing has been delivered for it either.
    expect(delivered()).toEqual(["token-for-one"]);
  });
});

describe("GuildAppPage, read inside an initiative", () => {
  beforeEach(() => {
    mint.mockImplementation((surfaceId: string) => Promise.resolve(handoff(surfaceId)));
  });

  it("offers the surfaces that asked to render here, and no others", async () => {
    const { GuildAppPage } = await import("./GuildAppPage");
    renderPage(() => <GuildAppPage appId={1} initiativeId={4} viewer={ADMIN} />);

    await screen.findByTitle("Automations");
    // The two guild-wide tabs belong to the other page. One surface left means
    // no tab strip at all, so the name appears nowhere.
    expect(screen.queryByText("One")).toBeNull();
    expect(screen.queryByText("Two")).toBeNull();
    await waitFor(() => expect(mint).toHaveBeenCalledWith("inside", expect.anything()));
  });

  it("mints through the route that names the initiative", async () => {
    const { GuildAppPage } = await import("./GuildAppPage");
    renderPage(() => <GuildAppPage appId={1} initiativeId={4} viewer={ADMIN} />);

    await screen.findByTitle("Automations");
    await waitFor(() =>
      expect(mint).toHaveBeenCalledWith("inside", { scope: "initiative", initiativeId: 4 })
    );
  });

  it("says so plainly when nothing here is for this reader", async () => {
    // A plain member of the initiative: the only surface here names its
    // managers, so there is nothing to open and nothing to mint.
    const { GuildAppPage } = await import("./GuildAppPage");
    renderPage(() => <GuildAppPage appId={1} initiativeId={4} viewer={{ isGuildAdmin: false }} />);

    await screen.findByText(/nothing to show|no page of its own|has no page/i);
    expect(mint).not.toHaveBeenCalled();
  });
});
