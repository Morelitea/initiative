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
  ) => mint(surfaceId),
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
    ],
  },
};

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

describe("GuildAppPage", () => {
  it("hands the first surface's token to the frame that asked", async () => {
    mint.mockImplementation((surfaceId: string) => Promise.resolve(handoff(surfaceId)));
    const { GuildAppPage } = await import("./GuildAppPage");
    renderPage(() => <GuildAppPage appId={1} />);

    await screen.findByTitle("Automations");
    ready();
    await waitFor(() => expect(delivered()).toEqual(["token-for-one"]));
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
    renderPage(() => <GuildAppPage appId={1} />);

    await screen.findByTitle("Automations");
    ready(); // spends the first token
    await waitFor(() => expect(delivered()).toEqual(["token-for-one"]));

    ready(); // the embed reloaded: starts the re-mint that will go stale
    (await screen.findByText("Two")).click();
    await waitFor(() => expect(mint).toHaveBeenCalledWith("two"));

    // The held re-mint now answers, for a surface nobody is looking at.
    releaseStale(handoff("one"));
    await new Promise((resolve) => setTimeout(resolve, 0));

    // Unchanged: the stale token was dropped rather than handed to the frame
    // now showing the other surface. Surface two has minted but not been asked,
    // so nothing has been delivered for it either.
    expect(delivered()).toEqual(["token-for-one"]);
  });
});
