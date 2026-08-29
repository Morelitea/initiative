/**
 * Browsing the community directory.
 *
 * The load-bearing details are that the filter rail actually narrows the
 * request (rather than filtering client-side, which would only ever narrow the
 * current page), and that a guild the caller is already in offers a way in
 * rather than a second way to join.
 */
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildBanner } from "@/__tests__/factories";
import { renderPage } from "@/__tests__/helpers/render";
import type { CommunityGuildRead } from "@/api/generated/initiativeAPI.schemas";

import { CommunitiesPage } from "./CommunitiesPage";

const directoryFor = vi.fn();
const join = vi.fn();
const fetchNextPage = vi.fn();

vi.mock("@/hooks/useCommunities", () => ({
  useCommunityGuilds: (params: unknown, options?: unknown) => directoryFor(params, options),
  useJoinCommunityGuild: () => ({ mutateAsync: join, isPending: false }),
}));

// Whether this deployment has a directory at all is the platform owner's
// setting; everything below is about one that does, bar the test that says so.
const config = vi.hoisted(() => ({ communityDirectory: true }));

vi.mock("@/hooks/useAppConfig", () => ({
  useAppConfig: () => ({
    communityDirectoryEnabled: config.communityDirectory,
    isLoading: false,
  }),
}));

const community = (overrides: Partial<CommunityGuildRead> = {}): CommunityGuildRead => ({
  id: 1,
  name: "Riverside Players",
  description: "Community theatre.",
  icon_url: null,
  banner: buildBanner(),
  categories: ["art"],
  member_count: 12,
  online_count: 0,
  already_member: false,
  ...overrides,
});

const renderDirectory = (search: Record<string, unknown> = {}) =>
  renderPage(CommunitiesPage, { initialRoute: "/communities", routerSearch: search });

/** The infinite-query shape the page reads: pages of items plus the paging
 *  flags. `total` is how many matched, so it can exceed what is loaded. */
const directoryResult = (items: CommunityGuildRead[], overrides: Record<string, unknown> = {}) => ({
  data: { pages: [{ items, total: items.length }] },
  isLoading: false,
  isError: false,
  hasNextPage: false,
  isFetchingNextPage: false,
  fetchNextPage,
  ...overrides,
});

beforeEach(() => {
  vi.clearAllMocks();
  config.communityDirectory = true;
  directoryFor.mockReturnValue(directoryResult([community()]));
});

describe("CommunitiesPage", () => {
  it("carries the page's heading over the banner, which is itself decorative", async () => {
    const { container } = renderDirectory();

    expect(
      await screen.findByRole("heading", { level: 1, name: "Nobody builds a world alone" })
    ).toBeInTheDocument();
    // The words are DOM text laid over the image rather than baked into it, so
    // the image describes nothing on its own and stays out of the a11y tree.
    const banner = container.querySelector('img[src="/images/community-banner.webp"]');
    expect(banner).toHaveAttribute("alt", "");
    // The image's layer and the copy share one grid cell, so the copy is what
    // gives the banner its height: a translation that wraps to more lines on a
    // narrow screen opens the banner up rather than running past its edge.
    const ground = banner?.parentElement as HTMLElement | null;
    expect(ground?.style.gridRow).toBe("1");
    expect(
      (screen.getByRole("heading", { level: 1 }).parentElement as HTMLElement).style.gridRow
    ).toBe("1");
    // The picture covers whatever that comes to, rather than setting the
    // height itself and leaving a strip too short to read a heading on.
    expect(banner).toHaveClass("absolute", "inset-0", "object-cover");
  });

  it("says so, and asks nothing, where the owner runs no directory", async () => {
    config.communityDirectory = false;
    renderDirectory();

    expect(await screen.findByText("No community directory here")).toBeInTheDocument();
    // The endpoint refuses the request there, so the page must not make it.
    expect(directoryFor).toHaveBeenCalledWith(expect.anything(), { enabled: false });
  });

  it("reads a refusal as the off state, not a failed load", async () => {
    // A tab that was open when the owner switched the directory off still has
    // it cached as on: it asks, and the answer settles it.
    directoryFor.mockReturnValue(
      directoryResult([], {
        isError: true,
        error: {
          isAxiosError: true,
          response: { status: 403, data: { detail: "COMMUNITY_DIRECTORY_DISABLED" } },
        },
      })
    );
    renderDirectory();

    expect(await screen.findByText("No community directory here")).toBeInTheDocument();
    expect(screen.queryByText("Directory unavailable")).not.toBeInTheDocument();
  });

  it("still reports a directory that failed to load", async () => {
    directoryFor.mockReturnValue(directoryResult([], { isError: true, error: new Error("boom") }));
    renderDirectory();

    expect(await screen.findByText("Directory unavailable")).toBeInTheDocument();
  });

  it("shows a card per community", async () => {
    renderDirectory();

    expect(await screen.findByText("Riverside Players")).toBeInTheDocument();
    expect(screen.getByText("Community theatre.")).toBeInTheDocument();
    expect(screen.getByText("12 members")).toBeInTheDocument();
    expect(screen.getByText("Art & design")).toBeInTheDocument();
  });

  it("puts the guild's banner across the top of its card", async () => {
    directoryFor.mockReturnValue(
      directoryResult([
        community({ banner: buildBanner({ image_url: "/api/v1/guilds/1/image/abc" }) }),
      ])
    );

    const { container } = renderDirectory();

    await screen.findByText("Riverside Players");
    const banner = container.querySelector('img[src="/api/v1/guilds/1/image/abc"]');
    expect(banner).not.toBeNull();
    // Decorative: the card already says the guild's name beneath it.
    expect(banner).toHaveAttribute("alt", "");
  });

  it("uses the banner colour on a card whose guild set one instead", async () => {
    directoryFor.mockReturnValue(
      directoryResult([community({ banner: buildBanner({ color: "#2a9d8f" }) })])
    );

    const { container } = renderDirectory();

    await screen.findByText("Riverside Players");
    expect(container.querySelector('[style*="rgb(42, 157, 143)"]')).not.toBeNull();
  });

  it("gives a card with no artwork the colour its guild wears", async () => {
    directoryFor.mockReturnValue(directoryResult([community()]));

    const { container } = renderDirectory();

    await screen.findByText("Riverside Players");
    // The page's own hero artwork is the only image on the page...
    expect(container.querySelectorAll("img")).toHaveLength(1);
    // ...but the card still has a banner.
    expect(container.querySelector('[style*="rgb(37, 99, 235)"]')).not.toBeNull();
  });

  it("says who is there now beside how many there are", async () => {
    directoryFor.mockReturnValue(directoryResult([community({ online_count: 3 })]));
    renderDirectory();

    expect(await screen.findByText("3 online")).toBeInTheDocument();
    expect(screen.getByText("12 members")).toBeInTheDocument();
  });

  it("says nothing about presence in a guild nobody is in", async () => {
    renderDirectory();

    await screen.findByText("Riverside Players");
    expect(screen.queryByText("0 online")).not.toBeInTheDocument();
  });

  it("asks for everything until a category is picked", async () => {
    renderDirectory();

    await screen.findByText("Riverside Players");
    expect(directoryFor).toHaveBeenCalledWith(
      { q: undefined, category: undefined },
      { enabled: true }
    );
  });

  // The filters are the sidebar's, and the address is what carries them here,
  // so what this page owes is that it asks for what the address says.
  it("narrows the request to the category in the address", async () => {
    renderDirectory({ category: "ttrpg" });

    await screen.findByText("Riverside Players");
    expect(directoryFor).toHaveBeenCalledWith(
      expect.objectContaining({ category: "ttrpg" }),
      expect.anything()
    );
  });

  // Below `lg` the sidebar that normally holds the search is off-canvas, so the
  // page carries a box of its own — the same one, writing the same address.
  it("searches from the page's own box", async () => {
    renderDirectory();
    await screen.findByText("Riverside Players");

    await userEvent.type(screen.getByRole("textbox", { name: "Search communities" }), "dice");

    await waitFor(() =>
      expect(directoryFor).toHaveBeenCalledWith(
        expect.objectContaining({ q: "dice" }),
        expect.anything()
      )
    );
  });

  it("narrows the request to the search in the address", async () => {
    renderDirectory({ q: "dice" });

    await screen.findByText("Riverside Players");
    expect(directoryFor).toHaveBeenCalledWith(
      expect.objectContaining({ q: "dice" }),
      expect.anything()
    );
  });

  it("says what nothing matched, naming the search it came from", async () => {
    directoryFor.mockReturnValue(directoryResult([]));
    renderDirectory({ q: "dice" });

    expect(await screen.findByText("Nothing matched")).toBeInTheDocument();
    expect(screen.getByText(/dice/)).toBeInTheDocument();
  });

  it("joins a community from its card", async () => {
    join.mockResolvedValue({ id: 1 });
    renderDirectory();
    await screen.findByText("Riverside Players");

    await userEvent.click(screen.getByRole("button", { name: "Join" }));

    await waitFor(() => expect(join).toHaveBeenCalledWith(1));
  });

  it("offers a way in, not a second join, for a guild already joined", async () => {
    directoryFor.mockReturnValue(directoryResult([community({ already_member: true })]));
    renderDirectory();

    expect(await screen.findByRole("button", { name: "Open" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Join" })).not.toBeInTheDocument();
  });

  it("distinguishes an unreachable directory from an empty one", async () => {
    directoryFor.mockReturnValue(directoryResult([], { data: undefined, isError: true }));
    renderDirectory();

    expect(await screen.findByText("Directory unavailable")).toBeInTheDocument();
    expect(screen.queryByText("No communities yet")).not.toBeInTheDocument();
  });

  it("says nobody has listed a guild when the directory is genuinely empty", async () => {
    directoryFor.mockReturnValue(directoryResult([]));
    renderDirectory();

    expect(await screen.findByText("No communities yet")).toBeInTheDocument();
  });

  it("fetches the next page rather than asking for a bigger one", async () => {
    // A growing page_size runs into the endpoint's 60-per-page ceiling and
    // takes the whole grid down with it, so "show more" pages instead.
    directoryFor.mockReturnValue(directoryResult([community()], { hasNextPage: true }));
    renderDirectory();

    await userEvent.click(await screen.findByRole("button", { name: "Show more" }));

    await waitFor(() => expect(fetchNextPage).toHaveBeenCalled());
    expect(directoryFor).not.toHaveBeenCalledWith(
      expect.objectContaining({ page_size: expect.anything() }),
      expect.anything()
    );
  });

  it("offers no more once every match is on screen", async () => {
    directoryFor.mockReturnValue(directoryResult([community()], { hasNextPage: false }));
    renderDirectory();

    await screen.findByText("Riverside Players");
    expect(screen.queryByRole("button", { name: "Show more" })).not.toBeInTheDocument();
  });
});
