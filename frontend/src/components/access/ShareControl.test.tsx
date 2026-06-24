import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildInitiative, buildInitiativeMember } from "@/__tests__/factories/initiative.factory";
import { buildUserPublic } from "@/__tests__/factories/user.factory";
import { renderWithProviders } from "@/__tests__/helpers/render";
import type {
  InitiativeRoleRead,
  ResourceGrantSchema,
} from "@/api/generated/initiativeAPI.schemas";

// ── Mock the data hooks ShareControl depends on ──────────────────────────────
// The component only reads ``.data`` off each query, so a simple stub is enough
// and keeps the test free of network/MSW plumbing.

const alice = buildUserPublic({ id: 101, full_name: "Alice", email: "alice@example.com" });
const bob = buildUserPublic({ id: 102, full_name: "Bob", email: "bob@example.com" });

const initiative = buildInitiative({
  id: 1,
  members: [buildInitiativeMember({ user: alice }), buildInitiativeMember({ user: bob })],
});

const roles: InitiativeRoleRead[] = [
  {
    id: 201,
    name: "player",
    display_name: "Player",
    is_builtin: false,
    is_manager: false,
    override_share_restrictions: false,
    position: 0,
    permissions: {},
    member_count: 2,
  },
  {
    id: 202,
    name: "project_manager",
    display_name: "Project Manager",
    is_builtin: true,
    is_manager: true,
    override_share_restrictions: true,
    position: 1,
    permissions: {},
    member_count: 1,
  },
];

vi.mock("@/hooks/useInitiatives", () => ({
  useInitiative: () => ({ data: initiative }),
}));

vi.mock("@/hooks/useInitiativeRoles", () => ({
  useInitiativeRoles: () => ({ data: roles }),
}));

import { ShareControl } from "./ShareControl";

describe("ShareControl", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders 'All members' mode when an all_initiative_members grant is present", () => {
    const grants: ResourceGrantSchema[] = [{ all_initiative_members: true, level: "read" }];

    renderWithProviders(<ShareControl initiativeId={1} grants={grants} onChange={vi.fn()} />);

    // The general-access select shows the "All initiative members" option as
    // selected; the People/Roles lists are hidden in this mode.
    expect(screen.getByText("All initiative members")).toBeInTheDocument();
    expect(screen.queryByText("People")).not.toBeInTheDocument();
    expect(screen.queryByText("Roles")).not.toBeInTheDocument();
  });

  it("switching Share to 'Restricted' calls onChange with the user/role grants (no all-members)", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    // Start in All-members mode so there are no user/role grants to carry over.
    const grants: ResourceGrantSchema[] = [{ all_initiative_members: true, level: "read" }];

    renderWithProviders(<ShareControl initiativeId={1} grants={grants} onChange={onChange} />);

    // Open the Share mode picker (the green general-access bar) and pick "Restricted".
    await user.click(screen.getByRole("button", { name: /All initiative members/i }));
    await user.click(await screen.findByRole("button", { name: /Restricted/i }));

    expect(onChange).toHaveBeenCalledTimes(1);
    const next = onChange.mock.calls[0][0] as ResourceGrantSchema[];
    expect(next.some((g) => g.all_initiative_members)).toBe(false);
    // No prior user/role grants existed, so the restricted list is empty.
    expect(next).toEqual([]);
  });

  it("in restricted mode, adding a person calls onChange including a {user_id, level:'read'} grant", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    // Restricted mode = no all_initiative_members grant.
    const grants: ResourceGrantSchema[] = [];

    renderWithProviders(<ShareControl initiativeId={1} grants={grants} onChange={onChange} />);

    // Open the "Add people" picker and select Alice.
    await user.click(screen.getByRole("button", { name: "Add people" }));
    const aliceOption = await screen.findByText("Alice");
    await user.click(aliceOption);

    expect(onChange).toHaveBeenCalledTimes(1);
    const next = onChange.mock.calls[0][0] as ResourceGrantSchema[];
    expect(next).toContainEqual({ user_id: 101, level: "read" });
  });

  it("renders a full-access role as a locked, non-removable Editor in restricted mode", () => {
    // Restricted mode (no all-members grant) and no stored role grant for the PM
    // role — its presence in the Roles list is purely from override_share_restrictions.
    const onChange = vi.fn();

    renderWithProviders(<ShareControl initiativeId={1} grants={[]} onChange={onChange} />);

    const rolesSection = screen.getByText("Roles").closest("div")?.parentElement as HTMLElement;
    expect(within(rolesSection).getByText("Project Manager")).toBeInTheDocument();
    expect(within(rolesSection).getByText("Full access")).toBeInTheDocument();
    expect(within(rolesSection).getByText("Editor")).toBeInTheDocument();
    // No remove control — a full-access role can't be removed from sharing.
    expect(within(rolesSection).queryByRole("button", { name: "Remove" })).not.toBeInTheDocument();
  });

  it("shows the owner as a fixed, non-editable row when ownerId is given", () => {
    const grants: ResourceGrantSchema[] = [];

    renderWithProviders(
      <ShareControl initiativeId={1} grants={grants} onChange={vi.fn()} ownerId={101} />
    );

    // Owner row appears under People with an "Owner" badge and no controls.
    const peopleSection = screen.getByText("People").closest("div")?.parentElement;
    expect(peopleSection).toBeTruthy();
    expect(within(peopleSection as HTMLElement).getByText("Alice")).toBeInTheDocument();
    expect(within(peopleSection as HTMLElement).getByText("Owner")).toBeInTheDocument();
  });
});
