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

import type {
  ContactGrantRead,
  ContactGuildSection,
  ContactRead,
  DmPolicy,
} from "@/api/generated/initiativeAPI.schemas";
import { routeTree } from "@/routeTree.gen";

import { renderPage } from "./helpers/render";

const CONTACTS_ROUTE_ID = "/_serverRequired/_authenticated/contacts";

const mocks = vi.hoisted(() => ({
  sections: vi.fn(),
  favorites: vi.fn(),
  toggle: vi.fn(),
  sectionPage: vi.fn(),
  prefetch: vi.fn(),
  dmSettings: vi.fn(),
  updateDm: vi.fn(),
  connections: vi.fn(),
  messages: vi.fn(),
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

// The reader's own policy decides whether the page has anything to list, so
// every test below states it. The default is an account that answered its age
// and let its communities in — the one whose sections have members.
vi.mock("@/hooks/useDirectMessages", async (importOriginal) => ({
  // Spread rather than listed: the row's actions menu reads several more of
  // these, and a mock that had to name every one would break on the next hook
  // added rather than on anything this file is about. The four below are the
  // ones a test here steers; the rest run for real, against the handlers.
  ...(await importOriginal<Record<string, unknown>>()),
  useDmSettings: () => mocks.dmSettings(),
  useUpdateDmSettings: () => ({ mutate: mocks.updateDm, isPending: false }),
  useConnections: () => mocks.connections(),
  useMessageRequests: () => mocks.messages(),
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

/** The reader's own direct-message settings, as the page reads them. */
const reader = (overrides: { age_confirmed_at?: string | null; dm_policy?: DmPolicy } = {}) =>
  mocks.dmSettings.mockReturnValue({
    data: {
      age_confirmed_at: "2020-01-01T00:00:00Z",
      dm_policy: "community" as DmPolicy,
      communities: [{ guild_id: 1, name: "Ravenloft Table", icon_url: null, enabled: false }],
      ...overrides,
    },
  });

let nextGrantId = 500;
const grant = (overrides: Partial<ContactGrantRead> = {}): ContactGrantRead => ({
  user_id: nextGrantId++,
  username: `grant${nextGrantId}`,
  discriminator: 4321,
  avatar_url: null,
  status: "active",
  presence: "offline",
  state: "accepted",
  outgoing: false,
  created_at: "2026-01-01T00:00:00Z",
  responded_at: "2026-01-02T00:00:00Z",
  ...overrides,
});

/** What the two grant lists hold. Empty unless a test says otherwise. */
const grants = (connections: ContactGrantRead[] = [], messages: ContactGrantRead[] = []) => {
  mocks.connections.mockReturnValue({
    data: { accepted: connections, incoming: [], outgoing: [] },
  });
  mocks.messages.mockReturnValue({ data: { accepted: messages, incoming: [], outgoing: [] } });
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
  reader();
  grants();
  nextGrantId = 500;
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

  it("says a page failed rather than claiming the community is empty", async () => {
    answer([section({ guild_id: 1, guild_name: "Big Table", items: people(1), total_count: 25 })]);
    mocks.sectionPage.mockImplementation((_guildId: number, page: number) =>
      page === 2
        ? { data: undefined, isPending: false, isPlaceholderData: false, isError: true }
        : pendingPage
    );
    await renderContacts();

    await userEvent.click(await screen.findByRole("button", { name: "Next" }));

    expect(await screen.findByText("That page didn't load.")).toBeInTheDocument();
    // The empty-roster line would say the opposite of what is true.
    expect(screen.queryByText("Nobody else is in this community yet.")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
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

  it("links a row at that person's profile, by handle", async () => {
    // Clicking a person lands on the person. Messaging them is a button there,
    // and it is there whether or not the channel is already open.
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

  describe("when the roster is empty because of the reader", () => {
    it("asks an unanswered account its age, and offers no policy while it is unanswered", async () => {
      reader({ age_confirmed_at: null, dm_policy: "private" });
      answer([section({ total_count: 0, items: [] })]);
      await renderContacts();

      expect(await screen.findByText(/Direct messages are off for this account/i)).toBeVisible();
      // Both conditions hold at once on a new account. Only the age panel may
      // show: the other one offers a route this account has no access to.
      expect(screen.queryByRole("button", { name: /Let my communities message me/i })).toBeNull();
    });

    it("puts the question in place of the page, not on top of it", async () => {
      // An unanswered account cannot reach anybody and nobody can reach it, in
      // any community. A table and a search field over that are furniture for
      // a list that can only ever be empty.
      reader({ age_confirmed_at: null });
      answer([section({ total_count: 0, items: [] })]);
      await renderContacts();

      expect(await screen.findByText(/Direct messages are off for this account/i)).toBeVisible();
      expect(screen.queryByText("Person")).toBeNull();
      expect(screen.queryByRole("searchbox")).toBeNull();
      expect(screen.queryByRole("region")).toBeNull();
    });

    it("asks the age question under a search term as well", async () => {
      // Searching does not make an unanswered account reachable, so the term
      // is not the reason the page is bare and the panel still belongs.
      reader({ age_confirmed_at: null });
      answer([section({ total_count: 0, items: [] })]);
      await renderContacts("anybody");

      expect(await screen.findByText(/Direct messages are off for this account/i)).toBeVisible();
    });

    it("explains a private account's empty communities and opens them in one click", async () => {
      reader({ dm_policy: "private" });
      answer([section({ guild_id: 1, total_count: 0, items: [] })]);
      await renderContacts();

      expect(screen.queryByText(/Direct messages are off for this account/i)).toBeNull();
      await userEvent.click(
        await screen.findByRole("button", { name: /Let my communities message me/i })
      );

      // The policy and nothing else: the community switches would stake the
      // write on a membership list fetched earlier, and this is the button
      // that must land.
      expect(mocks.updateDm).toHaveBeenCalledWith({ data: { dm_policy: "community" } });
    });

    it("says nothing until it knows what the settings are", async () => {
      // Absent settings read as an account that has answered nothing, and the
      // age panel is the one thing never to show somebody who has.
      mocks.dmSettings.mockReturnValue({ data: undefined });
      answer([section({ guild_id: 1, total_count: 0, items: [] })]);
      await renderContacts();

      expect(screen.queryByText(/Direct messages are off for this account/i)).toBeNull();
      expect(screen.queryByRole("button", { name: /Let my communities message me/i })).toBeNull();
    });

    it("says nothing about the reader while a search is running", async () => {
      reader({ dm_policy: "private" });
      answer([section({ guild_id: 1, total_count: 0, items: [] })]);
      await renderContacts("nobody");

      // An empty page under a term is about the term.
      expect(screen.queryByRole("button", { name: /Let my communities message me/i })).toBeNull();
    });

    it("never counts the people it is not listing", async () => {
      reader();
      answer([section({ guild_id: 1, total_count: 0, items: [] })]);
      await renderContacts();

      const line = await screen.findByText(/No one here is accepting messages right now/i);
      expect(line).toBeVisible();
      // The line describes other people's settings, which are not the
      // reader's to count.
      expect(line.textContent).not.toMatch(/\d/);
    });
  });

  describe("people no community introduced", () => {
    it("lists somebody you agreed to message and share nothing else with", async () => {
      // Two accounts on Anyone who accepted each other: no connection, no
      // community in common, and so no section on this page before now.
      const pen = grant({ username: "penpal" });
      grants([], [pen]);
      answer([]);
      await renderContacts();

      expect(await screen.findByText(/penpal/)).toBeVisible();
    });

    it("does not list a connection twice", async () => {
      // Accepting a connection opens the channel with it, so the same person
      // is in both lists the server sends.
      const lee = grant({ username: "leelee" });
      grants([lee], [lee]);
      answer([]);
      await renderContacts();

      expect(await screen.findByText("Connections")).toBeVisible();
      expect(screen.queryByText("Direct messages")).toBeNull();
      expect(screen.getAllByText(/leelee/)).toHaveLength(1);
    });

    it("does not send the reader to the generic empty page", async () => {
      grants([], [grant({ username: "penpal" })]);
      answer([]);
      await renderContacts();

      // In no communities and starring nobody, but not without contacts.
      expect(screen.queryByText(/Join a community/i)).toBeNull();
    });
  });
});
