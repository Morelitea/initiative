/**
 * Reaching somebody the conversation list cannot offer.
 *
 * Two ways in, one field. What is worth proving is that they stay separate:
 * a partial term narrows the rosters and offers nothing to connect to, and a
 * whole handle offers the connection without needing the person to appear in
 * any roster at all.
 */
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderPage } from "@/__tests__/helpers/render";
import type { ContactRead } from "@/api/generated/initiativeAPI.schemas";

const mocks = vi.hoisted(() => ({
  sections: vi.fn(),
  more: vi.fn(),
  permissions: vi.fn(),
  requestConnection: vi.fn(),
}));

vi.mock("@/hooks/useContacts", () => ({
  useContactSections: (search: string) => mocks.sections(search),
  useMoreCommunityContacts: (guildId: number, search: string, enabled: boolean) =>
    mocks.more(guildId, search, enabled),
}));

// The field's own debounce is not what is on trial, and waiting 250ms of fake
// time in every case only makes them slower.
vi.mock("@/hooks/useDebouncedValue", () => ({
  useDebouncedValue: (value: string) => value,
}));

vi.mock("@/hooks/useDirectMessages", async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  useDmPermissions: (ids: number[]) => mocks.permissions(ids),
  useRequestConnection: () => ({ mutate: mocks.requestConnection, isPending: false }),
}));

import { NewConversationDialog } from "./NewConversationDialog";

const person = (id: number, username: string): ContactRead => ({
  id,
  username,
  discriminator: 1234,
  full_name: null,
  avatar_url: null,
  status: "active",
  profile_decorations: {},
  guild_role: null,
  presence: "offline",
  shared_guild_ids: [7],
});

const section = (items: ContactRead[]) => ({
  guild_id: 7,
  guild_name: "Beyonders",
  icon_url: null,
  total_count: items.length,
  items,
  has_next: false,
});

const open = async () => {
  const result = renderPage(() => <NewConversationDialog />, { initialRoute: "/messages" });
  await userEvent.click(await screen.findByRole("button", { name: "Start a conversation" }));
  return result;
};

beforeEach(() => {
  vi.clearAllMocks();
  mocks.sections.mockReturnValue({
    data: { sections: [section([person(1, "ada")])], page: 1, page_size: 20 },
    isLoading: false,
  });
  mocks.more.mockReturnValue({
    data: undefined,
    isSuccess: false,
    isFetching: false,
    hasNextPage: false,
    fetchNextPage: vi.fn(),
  });
  mocks.permissions.mockReturnValue({
    data: { permissions: { "1": { permission: "may_request", may_connect: true } } },
  });
});

describe("NewConversationDialog", () => {
  it("lists the people you share a community with, under that community", async () => {
    await open();

    expect(await screen.findByRole("heading", { name: /Beyonders/ })).toBeVisible();
    expect(screen.getByText("ada")).toBeVisible();
    expect(screen.getByText("Ask to message")).toBeVisible();
  });

  it("goes to the conversation rather than deciding anything about it", async () => {
    const { router } = await open();
    await userEvent.click(screen.getByText("ada"));

    await waitFor(() => expect(router.state.location.pathname).toBe("/messages"));
    expect(router.state.location.search).toEqual({ with: "ada1234" });
  });

  it("offers no way in for somebody the server refuses, and no reason why", async () => {
    mocks.more.mockReturnValue({
      data: undefined,
      isSuccess: false,
      isFetching: false,
      hasNextPage: false,
      fetchNextPage: vi.fn(),
    });
    mocks.permissions.mockReturnValue({
      data: { permissions: { "1": { permission: "denied", may_connect: false } } },
    });
    await open();

    const row = screen.getByText("ada").closest("button") as HTMLButtonElement;
    expect(row).toBeDisabled();
    expect(screen.getByText("Not reachable")).toBeVisible();
  });

  it("waits for a whole handle before it offers a connection", async () => {
    await open();
    const field = screen.getByRole("textbox");

    await userEvent.type(field, "grace");
    expect(screen.queryByRole("button", { name: /Connect with/ })).not.toBeInTheDocument();

    await userEvent.type(field, "#0042");
    await userEvent.click(screen.getByRole("button", { name: "Connect with grace#0042" }));

    expect(mocks.requestConnection).toHaveBeenCalledWith(
      { data: { username: "grace", discriminator: 42 } },
      expect.anything()
    );
  });

  it("grows a long community rather than paging it, and only when asked", async () => {
    mocks.sections.mockReturnValue({
      data: {
        sections: [{ ...section([person(1, "ada")]), total_count: 42, has_next: true }],
        page: 1,
        page_size: 20,
      },
      isLoading: false,
    });
    await open();

    // Nothing fetched for a roster nobody has reached the bottom of.
    expect(mocks.more).toHaveBeenLastCalledWith(7, "", false);

    await userEvent.click(screen.getByRole("button", { name: "Show more" }));
    expect(mocks.more).toHaveBeenLastCalledWith(7, "", true);
  });

  it("appends the pages it fetched under the ones it already had", async () => {
    mocks.sections.mockReturnValue({
      data: {
        sections: [{ ...section([person(1, "ada")]), total_count: 42, has_next: true }],
        page: 1,
        page_size: 20,
      },
      isLoading: false,
    });
    mocks.more.mockReturnValue({
      data: { pages: [{ sections: [{ items: [person(2, "grace")] }] }] },
      isSuccess: true,
      isFetching: false,
      hasNextPage: false,
      fetchNextPage: vi.fn(),
    });
    await open();
    await userEvent.click(screen.getByRole("button", { name: "Show more" }));

    // The one already on screen stays where it was: a picker is read
    // downwards, and paging would take away the row just spotted.
    expect(await screen.findByText("ada")).toBeVisible();
    expect(screen.getByText("grace")).toBeVisible();
    // Nothing left to fetch, so nothing left to press.
    expect(screen.queryByRole("button", { name: "Show more" })).toBeNull();
  });

  it("puts an expanded community back to its first page under a new term", async () => {
    mocks.sections.mockReturnValue({
      data: {
        sections: [{ ...section([person(1, "ada")]), total_count: 42, has_next: true }],
        page: 1,
        page_size: 20,
      },
      isLoading: false,
    });
    await open();
    await userEvent.click(screen.getByRole("button", { name: "Show more" }));
    expect(mocks.more).toHaveBeenLastCalledWith(7, "", true);

    // A different term is a different set of people, and carrying the
    // expansion over would fetch a second page nobody asked for.
    await userEvent.type(screen.getByRole("textbox"), "gr");

    expect(mocks.more).toHaveBeenLastCalledWith(7, "gr", false);
  });

  it("asks the server for a term rather than filtering what it already had", async () => {
    await open();
    await userEvent.type(screen.getByRole("textbox"), "gra");

    expect(mocks.sections).toHaveBeenLastCalledWith("gra");
  });
});
