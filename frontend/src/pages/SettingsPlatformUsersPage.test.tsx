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
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildPage, buildUser } from "@/__tests__/factories";
import { renderPage } from "@/__tests__/helpers/render";
import type { OperatorUserRead, UserRead, UserRole } from "@/api/generated/initiativeAPI.schemas";
import { dateTimeFormat } from "@/lib/intl";

// The roster the mocked hook serves. Each test sets it, so no test depends on
// what another left behind.
const state = vi.hoisted(() => ({
  roster: [] as OperatorUserRead[],
  search: undefined as string | null | undefined,
  clearSecondFactor: vi.fn(),
  revokeApiKeys: vi.fn(),
  authenticatorAskedAtSignIn: true,
  passwordLoginEnabled: true,
}));

vi.mock("@/hooks/useAppConfig", () => ({
  useAppConfig: () => ({
    authenticatorAskedAtSignIn: state.authenticatorAskedAtSignIn,
    passwordLoginEnabled: state.passwordLoginEnabled,
  }),
}));

vi.mock("@/hooks/useOperatorUsers", () => ({
  usePlatformUsers: (params: { search?: string | null }) => {
    state.search = params.search;
    return { data: buildPage(state.roster), isLoading: false, isError: false };
  },
  useOperatorTriggerPasswordReset: () => ({ mutate: vi.fn(), isPending: false }),
  useOperatorResendVerification: () => ({ mutate: vi.fn(), isPending: false }),
  useOperatorSetUsername: () => ({ mutate: vi.fn(), isPending: false }),
  useOperatorClearAgeBlock: () => ({ mutate: vi.fn(), isPending: false }),
  useOperatorLiftSignInLock: () => ({ mutate: vi.fn(), isPending: false }),
  useOperatorClearSecondFactor: () => ({ mutate: state.clearSecondFactor, isPending: false }),
  useOperatorSetSuspension: () => ({ mutate: vi.fn(), isPending: false }),
  useOperatorReactivateUser: () => ({ mutate: vi.fn(), isPending: false }),
  useOperatorRestoreUser: () => ({ mutate: vi.fn(), isPending: false }),
  useOperatorUpdatePlatformRole: () => ({ mutate: vi.fn(), isPending: false }),
  useOperatorRemoveAvatar: () => ({ mutate: vi.fn(), isPending: false }),
  useOperatorRevokeApiKeys: () => ({ mutate: state.revokeApiKeys, isPending: false }),
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

/** Open the sheet for the account with this handle. */
const openSheet = async (handle = "member-one") => {
  await userEvent.click(
    await screen.findByRole("button", { name: new RegExp(`manage account @?${handle}`, "i") })
  );
  return screen.findByRole("dialog");
};

/** One lever in the sheet, whether it is labelled or captioned. */
const lever = (sheet: HTMLElement, name: string) =>
  within(sheet).queryByLabelText(name) ?? within(sheet).queryByText(name);

describe("SettingsPlatformUsersPage", () => {
  beforeEach(() => {
    state.roster = [];
    state.clearSecondFactor.mockClear();
    state.passwordLoginEnabled = true;
  });

  it("identifies an account by its handle, and shows no address or name", async () => {
    const rows = masked();
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
    expect(screen.queryByRole("button", { name: /^Name/ })).not.toBeInTheDocument();
  });

  it("marks an account whose password sign-in is turned off", async () => {
    const rows = masked();
    rows[1].sign_in_locked_until = "2026-09-24T12:00:00Z";
    renderRoster(rows);

    await screen.findByText("owner");
    expect(screen.getAllByText("Password sign-in off")).toHaveLength(1);
    expect(screen.getAllByText(/^Until .*2026/)).toHaveLength(1);
  });

  it("searches the server with a whole handle pasted in", async () => {
    const rows = masked();
    renderRoster(rows);

    const box = await screen.findByPlaceholderText(/filter by handle/i);
    const whole = `owner#${String(rows[0].discriminator).padStart(4, "0")}`;

    // What somebody pastes out of a ticket, sent as it was typed: the server
    // pins the one account that handle names.
    await userEvent.type(box, whole);

    await waitFor(() => expect(state.search).toBe(whole));
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

  it.each([true, false])(
    "offers a password reset only where passwords sign in (%s)",
    async (passwords) => {
      state.passwordLoginEnabled = passwords;
      renderRoster(masked(), buildUser({ role: "moderator" }));

      const triggers = await screen.findAllByRole("button", { name: /actions for/i });
      await userEvent.click(triggers[1]);
      const item = within(await screen.findByRole("menu")).queryByText("Reset password");
      expect(Boolean(item)).toBe(passwords);
    }
  );

  it.each<[string, UserRole, boolean, boolean, boolean]>([
    ["offers to clear an authenticator to a moderator", "moderator", true, true, true],
    ["offers nothing to clear on an account without one", "moderator", false, true, false],
    ["offers support no way to clear one", "support", true, true, false],
    // A passkey or single sign-on never asks for the code, so where nothing
    // else is permitted there is nothing to get past.
    ["offers nothing where signing in never asks for the code", "moderator", true, false, false],
  ])("%s", async (_label, role, enrolled, asked, offered) => {
    state.authenticatorAskedAtSignIn = asked;
    const rows = masked();
    rows[1].second_factor_enrolled = enrolled;
    renderRoster(rows, buildUser({ role }));

    const triggers = await screen.findAllByRole("button", { name: /actions for/i });
    await userEvent.click(triggers[1]);
    const item = within(await screen.findByRole("menu")).queryByText(
      "Clear two-factor authentication"
    );
    if (!offered) {
      expect(item).not.toBeInTheDocument();
      return;
    }

    // It signs them out everywhere, so it asks first.
    await userEvent.click(item as HTMLElement);
    const dialog = await screen.findByRole("alertdialog");
    expect(state.clearSecondFactor).not.toHaveBeenCalled();
    await userEvent.click(within(dialog).getByRole("button", { name: "Clear it" }));
    expect(state.clearSecondFactor).toHaveBeenCalledWith(rows[1].id);
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

  it.each<[string, UserRole, number, boolean]>([
    ["a moderator revokes the keys that still work", "moderator", 2, true],
    ["nothing to revoke on an account without working keys", "moderator", 0, false],
  ])("%s", async (_label, role, count, offered) => {
    state.revokeApiKeys.mockClear();
    const rows = masked();
    rows[1].api_key_count = count;
    renderRoster(rows, buildUser({ role }));

    const sheet = await openSheet();
    const revoke = within(sheet).queryByRole("button", { name: "Revoke" });
    if (!offered) {
      expect(revoke).not.toBeInTheDocument();
      return;
    }

    // Whatever runs on them stops at once, so it asks first.
    await userEvent.click(revoke as HTMLElement);
    const dialog = await screen.findByRole("alertdialog");
    expect(state.revokeApiKeys).not.toHaveBeenCalled();
    await userEvent.click(within(dialog).getByRole("button", { name: "Revoke" }));
    expect(state.revokeApiKeys).toHaveBeenCalledWith(rows[1].id);
  });

  it("offers nothing on an account above the viewer's own rung", async () => {
    renderRoster(masked(), buildUser({ role: "moderator" }));

    // Every action on an account is refused above the actor's rung, so the
    // owner's row offers a moderator nothing to open, while the member's does.
    await screen.findByText("owner");
    expect(
      screen.queryByRole("button", { name: /manage account @?owner/i })
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /manage account @?member-one/i })
    ).toBeInTheDocument();
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
    const expected = dateTimeFormat("en", {
      year: "numeric",
      month: "short",
      day: "numeric",
    }).format(new Date("2026-10-20T12:00:00Z"));
    expect(screen.getByText(`Erased ${expected}`)).toBeInTheDocument();
  });

  it("says so plainly where the deployment erases nobody", async () => {
    renderRoster(deleted(null));

    expect(await screen.findByText("Deleted")).toBeInTheDocument();
    expect(screen.getByText("Kept indefinitely")).toBeInTheDocument();
  });
});
