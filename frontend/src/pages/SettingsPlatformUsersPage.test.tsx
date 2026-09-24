/**
 * The platform roster, and the things about it that are not styling.
 *
 * The roster renders the address exactly as the API sent it and never
 * reassembles one — shortening is the server's job, and this page's job is to
 * not undo it. It identifies an account by its handle and nothing else: the
 * name somebody filled in is theirs, and an operator needs none of it to do
 * any of this.
 *
 * The levers themselves live in the sheet behind Manage, and each one is drawn
 * only for a viewer whose capability would carry it.
 */
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildUser } from "@/__tests__/factories";
import { renderPage } from "@/__tests__/helpers/render";
import type { OperatorUserRead, UserRead, UserRole } from "@/api/generated/initiativeAPI.schemas";

// The roster the mocked hook serves. Each test sets it, so no test depends on
// what another left behind.
const state = vi.hoisted(() => ({ roster: [] as OperatorUserRead[] }));

vi.mock("@/hooks/useOperatorUsers", () => ({
  usePlatformUsers: () => ({ data: state.roster, isLoading: false, isError: false }),
  useOperatorTriggerPasswordReset: () => ({ mutate: vi.fn(), isPending: false }),
  useOperatorSetUsername: () => ({ mutate: vi.fn(), isPending: false }),
  useOperatorClearAgeBlock: () => ({ mutate: vi.fn(), isPending: false }),
  useOperatorSetSuspension: () => ({ mutate: vi.fn(), isPending: false }),
  useOperatorReactivateUser: () => ({ mutate: vi.fn(), isPending: false }),
  useOperatorRestoreUser: () => ({ mutate: vi.fn(), isPending: false }),
  useOperatorUpdatePlatformRole: () => ({ mutate: vi.fn(), isPending: false }),
  useOperatorRemoveAvatar: () => ({ mutate: vi.fn(), isPending: false }),
  useExportPlatformUsersCsv: () => ({ mutate: vi.fn() }),
}));

import { SettingsPlatformUsersPage } from "./SettingsPlatformUsersPage";

// As the server serves it: addresses already reduced.
const masked = () =>
  [
    { ...buildUser({ role: "owner" }), email: "o***r@e***m", username: "owner" },
    { ...buildUser({ role: "member" }), email: "u***1@e***m", username: "member-one" },
  ] as unknown as OperatorUserRead[];

const renderRoster = (
  roster: OperatorUserRead[],
  viewer: UserRead = buildUser({ role: "owner" })
) => {
  state.roster = roster;
  return renderPage(() => <SettingsPlatformUsersPage />, { auth: { user: viewer } });
};

/** Open the sheet for the row at `index`. */
const openSheet = async (index = 1) => {
  const buttons = await screen.findAllByRole("button", { name: /manage account/i });
  await userEvent.click(buttons[index]);
  return screen.findByRole("dialog");
};

/** One lever in the sheet, whether it is labelled or captioned. */
const lever = (sheet: HTMLElement, name: string) =>
  within(sheet).queryByLabelText(name) ?? within(sheet).queryByText(name);

describe("SettingsPlatformUsersPage", () => {
  beforeEach(() => {
    state.roster = [];
  });

  it("identifies an account by its handle, and shows no address or name", async () => {
    const rows = masked();
    rows[1].full_name = "Wilhelmina Fitzgerald";
    renderRoster(rows);

    await screen.findByText("owner");
    // Not even the shortened form the server still sends: an operator does
    // not administer an account by its address.
    expect(screen.queryByText("o***r@e***m")).not.toBeInTheDocument();
    expect(screen.queryByText("u***1@e***m")).not.toBeInTheDocument();
    expect(screen.queryByText(/@example\.com/)).not.toBeInTheDocument();
    // A row is identified by handle, which is what the filter box searches.
    expect(screen.getByText("owner")).toBeInTheDocument();
    expect(screen.getByPlaceholderText(/filter by handle/i)).toBeInTheDocument();
    // The name somebody filled in is theirs, and an operator needs none of it.
    expect(screen.queryByText("Wilhelmina Fitzgerald")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Name/ })).not.toBeInTheDocument();
  });

  it("matches a whole handle pasted in, not just the name part", async () => {
    const rows = masked();
    renderRoster(rows);

    const box = await screen.findByPlaceholderText(/filter by handle/i);
    const whole = `owner#${String(rows[0].discriminator).padStart(4, "0")}`;

    // What somebody pastes out of a ticket. Filtering the bare name would
    // match nothing here, while still looking right for a typed prefix.
    await userEvent.type(box, whole);

    expect(screen.getByText("owner")).toBeInTheDocument();
    expect(screen.queryByText("member-one")).not.toBeInTheDocument();
  });

  it("offers a sort control on every identifying column, and only those", async () => {
    renderRoster(masked());

    for (const label of [/^User ID/, /^Handle/, /^Status/]) {
      expect(await screen.findByRole("button", { name: label })).toBeInTheDocument();
    }
    expect(screen.queryByRole("button", { name: /^Email/ })).not.toBeInTheDocument();
    // The role is decided in the sheet now, so it is not a column to sort by;
    // neither is the actions column something you can order rows by.
    expect(screen.queryByRole("button", { name: /^Role/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Actions$/ })).not.toBeInTheDocument();
  });

  it("puts the row's actions behind one menu instead of a run of buttons", async () => {
    renderRoster(masked());

    const triggers = await screen.findAllByRole("button", { name: /actions for/i });
    expect(triggers).toHaveLength(2);

    // Flat, these were up to seven buttons per row; none draws until asked.
    expect(screen.queryByText("Delete user")).not.toBeInTheDocument();

    await userEvent.click(triggers[1]);

    const menu = await screen.findByRole("menu");
    expect(menu).toHaveTextContent("Delete user");
    // Suspending is a setting the sheet holds, not a one-shot menu item.
    expect(menu).not.toHaveTextContent("Suspend");
  });
});

describe("SettingsPlatformUsersPage manage sheet", () => {
  beforeEach(() => {
    state.roster = [];
  });

  // ``content.moderate`` and ``users.manage`` are moderator-tier, but
  // ``roles.assign`` starts at operator — so each lever is drawn only for a
  // viewer whose capability would carry it, and only where the account has
  // something for it to act on.
  it.each<[string, UserRole, boolean, string[], string[]]>([
    [
      "an owner every lever, because an owner holds every capability",
      "owner",
      true,
      ["Username", "Profile picture", "Suspended", "Role"],
      [],
    ],
    [
      "a moderator everything but the ladder, which they cannot assign",
      "moderator",
      true,
      ["Username", "Suspended"],
      ["Role"],
    ],
    [
      "nothing to take the picture down with where there is no picture",
      "owner",
      false,
      ["Username"],
      ["Profile picture"],
    ],
  ])("offers %s", async (_label, role, hasAvatar, shown, hidden) => {
    const rows = masked();
    if (hasAvatar) rows[1].avatar_url = "/api/v1/users/2/avatar/abc";
    renderRoster(rows, buildUser({ role }));

    const sheet = await openSheet();

    for (const name of shown) expect(lever(sheet, name)).toBeInTheDocument();
    for (const name of hidden) expect(lever(sheet, name)).not.toBeInTheDocument();
  });

  it("offers support no way in at all, holding none of the three", async () => {
    renderRoster(masked(), buildUser({ role: "support" }));

    // Support can read the roster — that is ``users.read`` — and nothing here
    // writes to an account, so there is nothing to open.
    await screen.findByText("owner");
    expect(screen.queryByRole("button", { name: /manage account/i })).not.toBeInTheDocument();
  });
});

describe("an account on its way out", () => {
  const deleted = (purgeAt: string | null): OperatorUserRead[] => {
    const rows = masked();
    rows[1] = { ...rows[1], status: "deleted", purge_at: purgeAt };
    return rows;
  };

  it("is tagged, with the day it is erased", async () => {
    renderRoster(deleted("2026-10-20T12:00:00Z"));

    expect(await screen.findByText("Deleted")).toBeInTheDocument();
    // An instant, not a calendar day, so it is drawn in the reader's own
    // timezone — computed here the same way rather than written out.
    const expected = new Date("2026-10-20T12:00:00Z").toLocaleDateString("en", {
      year: "numeric",
      month: "short",
      day: "numeric",
    });
    expect(screen.getByText(`Erased ${expected}`)).toBeInTheDocument();
  });

  it("says so plainly where the deployment erases nobody", async () => {
    renderRoster(deleted(null));

    expect(await screen.findByText("Deleted")).toBeInTheDocument();
    expect(screen.getByText("Kept indefinitely")).toBeInTheDocument();
  });
});
