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
import { screen, within } from "@testing-library/react";
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
  fetchPage: vi.fn(),
}));

vi.mock("@/hooks/useContacts", () => ({
  CONTACTS_PAGE_SIZE: 20,
  useContactSections: (search: string) => mocks.sections(search),
  useFavoriteContacts: (search: string) => mocks.favorites(search),
  useToggleFavoriteContact: () => mocks.toggle,
  fetchContactPage: (...args: unknown[]) => mocks.fetchPage(...args),
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

const answer = (sections: ContactGuildSection[], favorites: ContactRead[] = []) => {
  mocks.sections.mockReturnValue({
    data: { sections, page: 1, page_size: 20 },
    isLoading: false,
  });
  mocks.favorites.mockReturnValue({
    data: { items: favorites, total_count: favorites.length },
    isLoading: false,
  });
};

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

beforeEach(() => {
  vi.clearAllMocks();
  nextId = 1;
  answer([]);
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
    expect(screen.queryByLabelText(/Also in/)).not.toBeInTheDocument();
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

  it("offers more of a community only while more remains", async () => {
    answer([
      section({ guild_id: 1, guild_name: "Big Table", items: [contact()], has_next: true }),
      section({ guild_id: 2, guild_name: "Small Table", items: [contact()], has_next: false }),
    ]);
    await renderContacts();

    expect(await screen.findAllByRole("button", { name: "Show more" })).toHaveLength(1);
  });

  it("appends the next page of a community without touching the others", async () => {
    const first = contact({ username: "aaa" });
    answer([section({ guild_id: 1, items: [first], total_count: 2, has_next: true })]);
    mocks.fetchPage.mockResolvedValue(
      section({ guild_id: 1, items: [contact({ username: "zzz" })], has_next: false })
    );
    await renderContacts();

    await userEvent.click(await screen.findByRole("button", { name: "Show more" }));

    expect(mocks.fetchPage).toHaveBeenCalledWith(1, 2, "");
    expect(await screen.findByText("zzz")).toBeInTheDocument();
    // The first page is still there — this appends rather than replaces.
    expect(screen.getByText("aaa")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Show more" })).not.toBeInTheDocument();
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
