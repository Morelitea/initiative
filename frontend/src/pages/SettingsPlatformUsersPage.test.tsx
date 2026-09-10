/**
 * The platform roster, and the two things about it that are not styling.
 *
 * The roster renders the address exactly as the API sent it and never
 * reassembles one — shortening is the server's job, and this page's job is to
 * not undo it. And the row's actions live behind a menu, so the destructive
 * one is not sitting under the finger reaching for Export.
 */
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildUser } from "@/__tests__/factories";
import { renderPage } from "@/__tests__/helpers/render";
import type { AdminUserRead } from "@/api/generated/initiativeAPI.schemas";

// The roster the mocked hook serves. Each test sets it, so no test depends on
// what another left behind.
const state = vi.hoisted(() => ({ roster: [] as AdminUserRead[] }));

vi.mock("@/hooks/useAdmin", () => ({
  usePlatformUsers: () => ({ data: state.roster, isLoading: false, isError: false }),
  usePlatformAdminCount: () => ({ data: { count: 2 } }),
  useAdminTriggerPasswordReset: () => ({ mutate: vi.fn(), isPending: false }),
  useAdminSetUsername: () => ({ mutate: vi.fn(), isPending: false }),
  useAdminClearAgeBlock: () => ({ mutate: vi.fn(), isPending: false }),
  useAdminSetSuspension: () => ({ mutate: vi.fn(), isPending: false }),
  useAdminReactivateUser: () => ({ mutate: vi.fn(), isPending: false }),
  useAdminUpdatePlatformRole: () => ({ mutate: vi.fn(), isPending: false }),
  useExportPlatformUsersCsv: () => ({ mutate: vi.fn() }),
}));

import { SettingsPlatformUsersPage } from "./SettingsPlatformUsersPage";

// As the server serves it: addresses already reduced.
const masked = () =>
  [
    { ...buildUser({ role: "owner" }), email: "o***r@e***m", username: "owner" },
    { ...buildUser({ role: "member" }), email: "u***1@e***m", username: "member-one" },
  ] as unknown as AdminUserRead[];

// Wide enough to tell a real ordering from an accidental one: by rank these
// run member → support → operator, which is neither the order they are given
// in nor their alphabetical order.
const ranked = () =>
  [
    { ...buildUser({ role: "operator" }), username: "carol", full_name: "Carol" },
    { ...buildUser({ role: "member" }), username: "alice", full_name: "Alice" },
    { ...buildUser({ role: "support" }), username: "bob", full_name: "Bob" },
  ] as unknown as AdminUserRead[];

const renderRoster = (roster: AdminUserRead[]) => {
  state.roster = roster;
  return renderPage(() => <SettingsPlatformUsersPage />, {
    auth: { user: buildUser({ role: "owner" }) },
  });
};

const rowText = () =>
  screen
    .getAllByRole("row")
    .slice(1) // drop the header row
    .map((row) => row.textContent ?? "");

const orderOf = (rows: string[], ...handles: string[]) =>
  handles.map((handle) => rows.findIndex((row) => row.includes(handle)));

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

  it("puts the row's actions behind one menu instead of a run of buttons", async () => {
    renderRoster(masked());

    const triggers = await screen.findAllByRole("button", { name: /actions for/i });
    expect(triggers).toHaveLength(2);

    // Flat, these were up to seven buttons per row; none draws until asked.
    expect(screen.queryByText("Suspend")).not.toBeInTheDocument();

    await userEvent.click(triggers[1]);

    const menu = await screen.findByRole("menu");
    expect(menu).toHaveTextContent("Suspend");
    expect(menu).toHaveTextContent("Delete user");
  });
});

describe("SettingsPlatformUsersPage sorting", () => {
  beforeEach(() => {
    state.roster = [];
  });

  it("offers a sort control on every identifying column", async () => {
    renderRoster(ranked());

    // Each of these used to be plain header text; only Email had a control.
    for (const label of [/^User ID/, /^Handle/, /^Name/, /^Email/, /^Role/, /^Status/]) {
      expect(await screen.findByRole("button", { name: label })).toBeInTheDocument();
    }
    // The actions column is not something you can order rows by.
    expect(screen.queryByRole("button", { name: /^Actions$/ })).not.toBeInTheDocument();
  });

  it("orders roles by privilege rather than alphabetically", async () => {
    renderRoster(ranked());

    await userEvent.click(await screen.findByRole("button", { name: /^Role/ }));

    // member → support → operator. Alphabetically that would be member,
    // operator, support — which is the ordering being ruled out.
    const [alice, bob, carol] = orderOf(rowText(), "alice", "bob", "carol");
    expect(alice).toBeLessThan(bob);
    expect(bob).toBeLessThan(carol);
  });

  it("orders by handle when asked", async () => {
    renderRoster(ranked());

    await userEvent.click(await screen.findByRole("button", { name: /^Handle/ }));

    const [alice, carol] = orderOf(rowText(), "alice", "carol");
    expect(alice).toBeLessThan(carol);
  });

  it("orders by name when asked", async () => {
    renderRoster(ranked());

    await userEvent.click(await screen.findByRole("button", { name: /^Name/ }));

    const [alice, carol] = orderOf(rowText(), "Alice", "Carol");
    expect(alice).toBeLessThan(carol);
  });
});
