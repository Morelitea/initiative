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

import { renderPage } from "@/__tests__/helpers/render";
import type { CommunityGuildRead } from "@/api/generated/initiativeAPI.schemas";

import { CommunitiesPage } from "./CommunitiesPage";

const directoryFor = vi.fn();
const join = vi.fn();
const fetchNextPage = vi.fn();

vi.mock("@/hooks/useCommunities", () => ({
  useCommunityGuilds: (params: unknown) => directoryFor(params),
  useJoinCommunityGuild: () => ({ mutateAsync: join, isPending: false }),
}));

const community = (overrides: Partial<CommunityGuildRead> = {}): CommunityGuildRead => ({
  id: 1,
  name: "Riverside Players",
  description: "Community theatre.",
  icon_base64: null,
  categories: ["art"],
  member_count: 12,
  already_member: false,
  ...overrides,
});

const renderDirectory = () => renderPage(CommunitiesPage, { initialRoute: "/communities" });

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
  directoryFor.mockReturnValue(directoryResult([community()]));
});

describe("CommunitiesPage", () => {
  it("shows a card per community", async () => {
    renderDirectory();

    expect(await screen.findByText("Riverside Players")).toBeInTheDocument();
    expect(screen.getByText("Community theatre.")).toBeInTheDocument();
    expect(screen.getByText("12 members")).toBeInTheDocument();
    // The same label is also a filter in the rail, so pin this to the card
    // badge (a div) rather than the rail entry (a button).
    expect(screen.getByText("Art & design", { selector: "div" })).toBeInTheDocument();
  });

  it("asks for everything until a category is picked", async () => {
    renderDirectory();

    await screen.findByText("Riverside Players");
    expect(directoryFor).toHaveBeenCalledWith({ q: undefined, category: undefined });
  });

  it("narrows the request when a category is picked", async () => {
    renderDirectory();
    await screen.findByText("Riverside Players");

    await userEvent.click(screen.getByRole("button", { name: "Tabletop RPG" }));

    await waitFor(() => {
      expect(directoryFor).toHaveBeenCalledWith(expect.objectContaining({ category: "ttrpg" }));
    });
  });

  it("narrows the request when a search is typed", async () => {
    renderDirectory();
    await screen.findByText("Riverside Players");

    await userEvent.type(screen.getByLabelText("Search communities"), "dice");

    await waitFor(() => {
      expect(directoryFor).toHaveBeenCalledWith(expect.objectContaining({ q: "dice" }));
    });
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
      expect.objectContaining({ page_size: expect.anything() })
    );
  });

  it("offers no more once every match is on screen", async () => {
    directoryFor.mockReturnValue(directoryResult([community()], { hasNextPage: false }));
    renderDirectory();

    await screen.findByText("Riverside Players");
    expect(screen.queryByRole("button", { name: "Show more" })).not.toBeInTheDocument();
  });
});
