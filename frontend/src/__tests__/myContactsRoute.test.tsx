/**
 * My Contacts, through the router the app ships.
 *
 * The page is only useful if it is reachable: the generated route tree has to
 * serve `/contacts` — outside the community tree, because it spans all of
 * them — and load the page from its own chunk. A test that mounts the
 * component directly proves neither, so this one goes through the tree and
 * preloads the route's own component.
 */
import { createRouter } from "@tanstack/react-router";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ContactGuildSection, ContactRead } from "@/api/generated/initiativeAPI.schemas";
import { routeTree } from "@/routeTree.gen";

import { renderPage } from "./helpers/render";

const CONTACTS_ROUTE_ID = "/_serverRequired/_authenticated/contacts";

const mocks = vi.hoisted(() => ({
  sections: vi.fn(),
  favorites: vi.fn(),
  toggle: vi.fn(),
  sectionPage: vi.fn(),
  prefetch: vi.fn(),
}));

vi.mock("@/hooks/useContacts", () => ({
  CONTACTS_PAGE_SIZE: 20,
  useContactSections: (search: string) => mocks.sections(search),
  useFavoriteContacts: (search: string) => mocks.favorites(search),
  useToggleFavoriteContact: () => mocks.toggle,
  useContactSectionPage: (guildId: number, page: number, search: string) =>
    mocks.sectionPage(guildId, page, search),
  usePrefetchContactSectionPage: () => mocks.prefetch,
  contactsPrefetch: () => ({ sections: {}, favorites: {} }),
}));

// The collapse preference is a server round-trip this page does not need to
// prove; it stands in as open-by-default.
vi.mock("@/hooks/useViewPreference", () => ({
  VIEW_PREFERENCES_QUERY_KEY: ["user-view-preferences"],
  useViewPreference: (_scope: string, fallback: unknown) => [fallback, vi.fn(), { isLoaded: true }],
}));

const router = createRouter({ routeTree });

let nextId = 1;
const contact = (overrides: Partial<ContactRead> = {}): ContactRead => ({
  id: nextId++,
  username: `person${nextId}`,
  discriminator: 1234,
  full_name: null,
  avatar_url: null,
  status: "active",
  presence: "offline",
  shared_guild_ids: [],
  ...overrides,
});

const section = (overrides: Partial<ContactGuildSection> = {}): ContactGuildSection => ({
  guild_id: 1,
  guild_name: "Ravenloft Table",
  icon_url: null,
  total_count: 1,
  items: [],
  has_next: false,
  ...overrides,
});

const answer = (
  sections: ContactGuildSection[],
  favorites: ContactRead[] = [],
  state: { isLoading?: boolean; isFetching?: boolean } = {}
) => {
  const flags = { isLoading: false, isFetching: false, ...state };
  mocks.sections.mockReturnValue({
    data: { sections, page: 1, page_size: 20 },
    ...flags,
  });
  mocks.favorites.mockReturnValue({
    data: { items: favorites, total_count: favorites.length },
    ...flags,
  });
};

/** A section page that has not arrived — what every page past the first is. */
const pendingPage = { data: undefined, isPending: true, isPlaceholderData: false };

const contactsPage = async () => {
  const route = router.routesById[CONTACTS_ROUTE_ID];
  const Page = route.options.component as React.ComponentType & {
    preload?: () => Promise<unknown>;
  };
  // The dynamic import the route is declared with: a moved page or a renamed
  // export fails here rather than at a click.
  await Page.preload?.();
  return Page;
};

const renderContacts = async (q?: string) => {
  const Page = await contactsPage();
  return renderPage(Page, {
    initialRoute: "/contacts",
    ...(q ? { routerSearch: { q } } : {}),
  });
};

const people = (count: number) => Array.from({ length: count }, () => contact());

beforeEach(() => {
  vi.clearAllMocks();
  nextId = 1;
  answer([]);
  mocks.sectionPage.mockReturnValue(pendingPage);
});

describe("My Contacts", () => {
  it("is an address the shipped route tree serves", () => {
    const matches = router.matchRoutes({ pathname: "/contacts", search: {} }, { preload: true });
    expect(String(matches.at(-1)?.routeId)).toBe(CONTACTS_ROUTE_ID);
  });

  it("renders communities in the order the server sent them", async () => {
    answer([
      section({ guild_id: 7, guild_name: "Sunday Sci-Fi" }),
      section({ guild_id: 2, guild_name: "Ravenloft Table" }),
      section({ guild_id: 5, guild_name: "Homebrew Workshop" }),
    ]);
    await renderContacts();

    // Rail order is decided server-side, so the page must not re-sort by name
    // or by id — it renders the array as received.
    const headings = await screen.findAllByRole("button", { name: /Sci-Fi|Ravenloft|Homebrew/ });
    expect(headings.map((node) => node.textContent)).toEqual([
      expect.stringContaining("Sunday Sci-Fi"),
      expect.stringContaining("Ravenloft Table"),
      expect.stringContaining("Homebrew Workshop"),
    ]);
  });

  it("names the columns once, above every section", async () => {
    answer([section({ items: [contact({ username: "ada" })] })]);
    await renderContacts();

    await screen.findByText("ada");
    expect(screen.getByText("Person")).toBeInTheDocument();
    expect(screen.getByText("Name")).toBeInTheDocument();
    expect(screen.getByText("Also in")).toBeInTheDocument();
  });

  it("lists somebody under each community they are in", async () => {
    const ada = contact({ username: "ada", shared_guild_ids: [1, 2] });
    answer([
      section({ guild_id: 1, guild_name: "Ravenloft Table", items: [ada] }),
      section({ guild_id: 2, guild_name: "Sunday Sci-Fi", items: [ada] }),
    ]);
    await renderContacts();

    expect(await screen.findAllByText("ada")).toHaveLength(2);
  });

  it("points each appearance at the other communities, not its own", async () => {
    const ada = contact({ username: "ada", shared_guild_ids: [1, 2] });
    answer([
      section({ guild_id: 1, guild_name: "Ravenloft Table", items: [ada] }),
      section({ guild_id: 2, guild_name: "Sunday Sci-Fi", items: [ada] }),
    ]);
    await renderContacts();

    // Under Ravenloft the chip names Sunday Sci-Fi, and the other way round.
    expect(await screen.findByLabelText("Also in Sunday Sci-Fi")).toBeInTheDocument();
    expect(screen.getByLabelText("Also in Ravenloft Table")).toBeInTheDocument();
  });

  it("draws no chip for somebody in only this community", async () => {
    answer([section({ items: [contact({ username: "solo", shared_guild_ids: [1] })] })]);
    await renderContacts();

    await screen.findByText("solo");
    expect(screen.queryByLabelText(/Also in .+/)).not.toBeInTheDocument();
  });

  it("keeps every shared community on a Favorites row, which sits under none", async () => {
    const ada = contact({ username: "ada", shared_guild_ids: [1, 2] });
    answer(
      [
        section({ guild_id: 1, guild_name: "Ravenloft Table" }),
        section({ guild_id: 2, guild_name: "Sunday Sci-Fi" }),
      ],
      [ada]
    );
    await renderContacts();

    expect(
      await screen.findByLabelText("Also in Ravenloft Table, Sunday Sci-Fi")
    ).toBeInTheDocument();
  });

  it("stars somebody who is not starred, and unstars somebody who is", async () => {
    const starred = contact({ id: 10, username: "already" });
    const plain = contact({ id: 11, username: "notyet" });
    answer([section({ items: [starred, plain] })], [starred]);
    await renderContacts();

    await userEvent.click(await screen.findByRole("button", { name: /Add notyet.* favorites/ }));
    expect(mocks.toggle).toHaveBeenCalledWith(11, false);

    await userEvent.click(screen.getAllByRole("button", { name: /Remove already/ })[0]);
    expect(mocks.toggle).toHaveBeenCalledWith(10, true);
  });

  it("passes the term in the URL to both reads", async () => {
    answer([]);
    await renderContacts("ada");
    await screen.findByRole("heading", { name: "My Contacts" });

    expect(mocks.sections).toHaveBeenCalledWith("ada");
    expect(mocks.favorites).toHaveBeenCalledWith("ada");
  });

  it("keeps both pager buttons on screen, disabled where there is nowhere to go", async () => {
    answer([
      section({ guild_id: 1, guild_name: "Big Table", items: people(1), total_count: 25 }),
      section({ guild_id: 2, guild_name: "Small Table", items: people(1), total_count: 1 }),
    ]);
    await renderContacts();

    // Both sections carry a pager, whether or not they have a second page.
    const next = await screen.findAllByRole("button", { name: "Next" });
    expect(next).toHaveLength(2);
    expect(next[0]).toBeEnabled();
    expect(next[1]).toBeDisabled();

    const previous = screen.getAllByRole("button", { name: "Previous" });
    expect(previous).toHaveLength(2);
    for (const button of previous) expect(button).toBeDisabled();
  });

  it("says which slice of a community is on screen", async () => {
    answer([section({ guild_id: 1, items: people(1), total_count: 25 })]);
    await renderContacts();

    expect(await screen.findByText("1–20 of 25")).toBeInTheDocument();
  });

  it("replaces a community's rows with the next page, leaving the others", async () => {
    answer([
      section({
        guild_id: 1,
        guild_name: "Big Table",
        items: [contact({ username: "aaa" })],
        total_count: 25,
      }),
      section({ guild_id: 2, guild_name: "Small Table", items: [contact({ username: "stays" })] }),
    ]);
    mocks.sectionPage.mockImplementation((guildId: number, page: number) =>
      page === 2
        ? {
            data: {
              sections: [section({ guild_id: guildId, items: [contact({ username: "zzz" })] })],
            },
            isPending: false,
            isPlaceholderData: false,
          }
        : pendingPage
    );
    await renderContacts();

    const next = await screen.findAllByRole("button", { name: "Next" });
    await userEvent.click(next[0]);

    expect(mocks.sectionPage).toHaveBeenCalledWith(1, 2, "");
    expect(await screen.findByText("zzz")).toBeInTheDocument();
    // A page replaces the one before it, and no other section moved.
    expect(screen.queryByText("aaa")).not.toBeInTheDocument();
    expect(screen.getByText("stays")).toBeInTheDocument();
    expect(screen.getByText("21–25 of 25")).toBeInTheDocument();
  });

  it("returns a community to its first page under a new term", async () => {
    answer([section({ guild_id: 1, items: people(1), total_count: 25 })]);
    await renderContacts();

    await userEvent.click(await screen.findByRole("button", { name: "Next" }));
    expect(mocks.sectionPage).toHaveBeenLastCalledWith(1, 2, "");

    answer([section({ guild_id: 1, items: [contact({ username: "match" })], total_count: 1 })]);
    await userEvent.type(
      screen.getByRole("searchbox", { name: "Search everyone on this page" }),
      "match"
    );

    // The sections under a different term are a different set of people, so
    // page two of the old one is not a place to still be.
    await waitFor(() => expect(mocks.sectionPage).toHaveBeenLastCalledWith(1, 1, "match"));
    expect(await screen.findByText("match")).toBeInTheDocument();
  });

  it("pages the starred list, which arrives whole", async () => {
    const starred = people(21);
    answer([], starred);
    await renderContacts();

    const last = starred[20];
    expect(await screen.findByText("1–20 of 21")).toBeInTheDocument();
    expect(screen.queryByText(last.username as string)).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(await screen.findByText(last.username as string)).toBeInTheDocument();
  });

  it("explains the wait while a search crosses every community", async () => {
    answer([section({ items: [contact({ username: "ada" })] })], [], { isFetching: true });
    await renderContacts("ada");

    expect(await screen.findByText("Searching every community")).toBeInTheDocument();
    expect(screen.getByText(/one at a time/)).toBeInTheDocument();
  });

  it("says nothing about crossing communities when simply loading the page", async () => {
    answer([], [], { isLoading: true });
    await renderContacts();

    expect(await screen.findByText("Loading your contacts…")).toBeInTheDocument();
    expect(screen.queryByText("Searching every community")).not.toBeInTheDocument();
  });

  it("says so when a search matched nobody", async () => {
    answer([]);
    await renderContacts("nobody");

    expect(await screen.findByText("Nobody by that name")).toBeInTheDocument();
  });

  it("says something different when there is simply nobody yet", async () => {
    answer([]);
    await renderContacts();

    expect(await screen.findByText("Nobody here yet")).toBeInTheDocument();
  });

  it("links a row to that person's profile by handle", async () => {
    answer([section({ items: [contact({ username: "ada", discriminator: 42 })] })]);
    await renderContacts();

    const row = (await screen.findByText("ada")).closest("a");
    expect(row).toHaveAttribute("href", "/u/ada0042");
  });

  it("counts a community by its whole roster, not the page on screen", async () => {
    answer([
      section({ guild_id: 1, guild_name: "Big Table", items: [contact()], total_count: 31 }),
    ]);
    await renderContacts();

    const heading = await screen.findByRole("button", { name: /Big Table/ });
    expect(within(heading).getByText("31")).toBeInTheDocument();
  });
});
