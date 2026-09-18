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
import type { AdminUserRead, UserRead } from "@/api/generated/initiativeAPI.schemas";

// The roster the mocked hook serves. Each test sets it, so no test depends on
// what another left behind.
const state = vi.hoisted(() => ({ roster: [] as AdminUserRead[] }));

vi.mock("@/hooks/useAdmin", () => ({
  usePlatformUsers: () => ({ data: state.roster, isLoading: false, isError: false }),
  useAdminTriggerPasswordReset: () => ({ mutate: vi.fn(), isPending: false }),
  useAdminSetUsername: () => ({ mutate: vi.fn(), isPending: false }),
  useAdminClearAgeBlock: () => ({ mutate: vi.fn(), isPending: false }),
  useAdminSetSuspension: () => ({ mutate: vi.fn(), isPending: false }),
  useAdminReactivateUser: () => ({ mutate: vi.fn(), isPending: false }),
  useAdminUpdatePlatformRole: () => ({ mutate: vi.fn(), isPending: false }),
  useAdminRemoveAvatar: () => ({ mutate: vi.fn(), isPending: false }),
  useExportPlatformUsersCsv: () => ({ mutate: vi.fn() }),
}));

import { SettingsPlatformUsersPage } from "./SettingsPlatformUsersPage";

// As the server serves it: addresses already reduced.
const masked = () =>
  [
    { ...buildUser({ role: "owner" }), email: "o***r@e***m", username: "owner" },
    { ...buildUser({ role: "member" }), email: "u***1@e***m", username: "member-one" },
  ] as unknown as AdminUserRead[];

const renderRoster = (roster: AdminUserRead[], viewer: UserRead = buildUser({ role: "owner" })) => {
  state.roster = roster;
  return renderPage(() => <SettingsPlatformUsersPage />, { auth: { user: viewer } });
};

/** Open the sheet for the row at `index`. */
const openSheet = async (index = 1) => {
  const buttons = await screen.findAllByRole("button", { name: /manage account/i });
  await userEvent.click(buttons[index]);
  return screen.findByRole("dialog");
};

describe("SettingsPlatformUsersPage", () => {
  beforeEach(() => {
    state.roster = [];
  });

  it("shows the address exactly as the server masked it", async () => {
    renderRoster(masked());

    expect(await screen.findByText("o***r@e***m")).toBeInTheDocument();
    expect(screen.getByText("u***1@e***m")).toBeInTheDocument();
    // Nothing on the page reassembles a real address from what arrived.
    expect(screen.queryByText(/@example\.com/)).not.toBeInTheDocument();
  });

  it("identifies a row by handle, which is what the filter box searches", async () => {
    renderRoster(masked());

    expect(await screen.findByText("owner")).toBeInTheDocument();
    expect(screen.getByPlaceholderText(/filter by handle/i)).toBeInTheDocument();
  });

  it("matches a whole handle pasted in, not just the name part", async () => {
    const rows = masked();
    renderRoster(rows);

    const box = await screen.findByPlaceholderText(/filter by handle/i);
    const whole = `owner#${String(rows[0].discriminator).padStart(4, "0")}`;

    // What somebody pastes out of a ticket. Filtering the bare name would
    // match nothing here, while still looking right for a typed prefix.
    await userEvent.type(box, whole);

    expect(screen.getByText("o***r@e***m")).toBeInTheDocument();
    expect(screen.queryByText("u***1@e***m")).not.toBeInTheDocument();
  });

  it("never shows the name the account filled in", async () => {
    const rows = masked();
    rows[1].full_name = "Wilhelmina Fitzgerald";
    renderRoster(rows);

    await screen.findByText("u***1@e***m");
    expect(screen.queryByText("Wilhelmina Fitzgerald")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Name/ })).not.toBeInTheDocument();
  });

  it("offers a sort control on every identifying column, and only those", async () => {
    renderRoster(masked());

    for (const label of [/^User ID/, /^Handle/, /^Email/, /^Status/]) {
      expect(await screen.findByRole("button", { name: label })).toBeInTheDocument();
    }
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

  it("offers an owner every lever, because an owner holds every capability", async () => {
    const rows = masked();
    rows[1].avatar_url = "/api/v1/users/2/avatar/abc";
    renderRoster(rows);

    const sheet = await openSheet();

    expect(within(sheet).getByLabelText("Username")).toBeInTheDocument();
    expect(within(sheet).getByText("Profile picture")).toBeInTheDocument();
    expect(within(sheet).getByLabelText("Suspended")).toBeInTheDocument();
    expect(within(sheet).getByLabelText("Role")).toBeInTheDocument();
  });

  it("withholds the ladder from a moderator, who cannot assign roles", async () => {
    const rows = masked();
    rows[1].avatar_url = "/api/v1/users/2/avatar/abc";
    renderRoster(rows, buildUser({ role: "moderator" }));

    const sheet = await openSheet();

    // ``content.moderate`` and ``users.manage`` are moderator-tier...
    expect(within(sheet).getByLabelText("Username")).toBeInTheDocument();
    expect(within(sheet).getByLabelText("Suspended")).toBeInTheDocument();
    // ...but ``roles.assign`` starts at operator.
    expect(within(sheet).queryByLabelText("Role")).not.toBeInTheDocument();
  });

  it("offers support no way in at all, holding none of the three", async () => {
    renderRoster(masked(), buildUser({ role: "support" }));

    // Support can read the roster — that is ``users.read`` — and nothing here
    // writes to an account, so there is nothing to open.
    await screen.findByText("o***r@e***m");
    expect(screen.queryByRole("button", { name: /manage account/i })).not.toBeInTheDocument();
  });

  it("leaves the picture out when there is no picture to take down", async () => {
    // Default roster: avatar_url is null.
    renderRoster(masked());

    const sheet = await openSheet();

    expect(within(sheet).getByLabelText("Username")).toBeInTheDocument();
    expect(within(sheet).queryByText("Profile picture")).not.toBeInTheDocument();
  });
});
