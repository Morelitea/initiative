/**
 * The sidebar's people roster.
 *
 * The server decides who is listed and in what order; this draws the groups it
 * sends, counts each from the totals rather than the loaded page, and tells a
 * reader whose direct messages are private why they are missing from it.
 */
import { screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderPage } from "@/__tests__/helpers/render";
import type { GuildRosterMember, GuildRosterResponse } from "@/api/generated/initiativeAPI.schemas";
import { SidebarProvider } from "@/components/ui/sidebar";

import { PeopleSection } from "./PeopleSection";

const mocks = vi.hoisted(() => ({
  roster: vi.fn(),
  dmPolicy: "community" as string,
}));

vi.mock("@/hooks/useUsers", async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  useGuildRoster: () => mocks.roster(),
}));
vi.mock("@/hooks/useDirectMessages", async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  useDirectMessagesEnabled: () => true,
  useDmSettings: () => ({ data: { dm_policy: mocks.dmPolicy } }),
}));

const member = (overrides: Partial<GuildRosterMember>): GuildRosterMember => ({
  id: 1,
  username: "someone",
  discriminator: 1234,
  full_name: null,
  avatar_url: null,
  status: "active",
  guild_role: "member",
  profile_decorations: null,
  presence: "offline",
  custom_status: { emoji: null, text: null },
  ...overrides,
});

const page = (
  items: GuildRosterMember[],
  presence_counts: GuildRosterResponse["presence_counts"],
  has_next = false
) =>
  mocks.roster.mockReturnValue({
    data: {
      pages: [
        {
          items,
          presence_counts,
          total_count: items.length,
          page: 1,
          page_size: 50,
          has_next,
          has_prev: false,
        },
      ],
    },
    isLoading: false,
    hasNextPage: has_next,
  });

const render = () =>
  renderPage(() => (
    <SidebarProvider>
      <PeopleSection />
    </SidebarProvider>
  ));

beforeEach(() => {
  mocks.dmPolicy = "community";
});

describe("PeopleSection", () => {
  it("groups people by presence and counts each group from the totals", async () => {
    page(
      [
        member({ id: 1, username: "ada", presence: "online" }),
        member({
          id: 2,
          username: "bram",
          presence: "busy",
          guild_role: "admin",
          custom_status: { emoji: "🎧", text: "Heads down" },
        }),
        member({ id: 3, username: "cleo" }),
      ],
      { online: 1, idle: 0, busy: 1, offline: 40 },
      true
    );

    render();

    expect(await screen.findByText("Online — 1")).toBeInTheDocument();
    expect(screen.getByText("Busy — 1")).toBeInTheDocument();
    expect(screen.getByText("Offline — 40")).toBeInTheDocument();
    expect(screen.queryByText(/Idle/)).not.toBeInTheDocument();
    expect(screen.getByText("Heads down")).toBeInTheDocument();
    expect(screen.getByText("Admin")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Show more" })).toBeInTheDocument();
  });

  it("tells a reader with private direct messages why they are not listed", async () => {
    mocks.dmPolicy = "private";
    page([member({ id: 1, username: "ada", presence: "online" })], {
      online: 1,
      idle: 0,
      busy: 0,
      offline: 0,
    });

    render();

    expect(await screen.findByText(/your direct messages are private/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Change it" })).toHaveAttribute(
      "href",
      "/profile/privacy"
    );
  });

  it("says so when nobody is listed", async () => {
    page([], { online: 0, idle: 0, busy: 0, offline: 0 });

    render();

    expect(await screen.findByText(/Nobody is listed here yet/)).toBeInTheDocument();
  });
});
