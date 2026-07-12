import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildUser } from "@/__tests__/factories";
import { server } from "@/__tests__/helpers/msw-server";
import { renderWithProviders } from "@/__tests__/helpers/render";

import { AdminDeleteUserDialog } from "./AdminDeleteUserDialog";

const targetUser = buildUser({ id: 42, email: "sole-admin@example.com", status: "active" });

const eligibilityWithGuildBlocker = {
  can_delete: false,
  blockers: ["Sole admin of guild Lone Guild"],
  warnings: [],
  owned_projects: [],
  guild_blockers: [{ guild_id: 77, guild_name: "Lone Guild", other_members: [] }],
  initiative_blockers: [],
};

const eligibilityClear = {
  can_delete: true,
  blockers: [],
  warnings: [],
  owned_projects: [],
  guild_blockers: [],
  initiative_blockers: [],
};

describe("AdminDeleteUserDialog guild blocker resolution", () => {
  const deleteGuildSpy = vi.fn();

  beforeEach(() => {
    deleteGuildSpy.mockClear();
    let eligibilityCalls = 0;
    server.use(
      http.get("/api/v1/admin/users/42/deletion-eligibility", () => {
        eligibilityCalls += 1;
        // First check: blocked by the guild. After the guild is deleted the
        // refreshed check comes back clear.
        return HttpResponse.json(
          eligibilityCalls === 1 ? eligibilityWithGuildBlocker : eligibilityClear
        );
      }),
      http.delete("/api/v1/admin/guilds/77", ({ request }) => {
        deleteGuildSpy(new URL(request.url).searchParams.get("blocked_user_id"));
        return new HttpResponse(null, { status: 204 });
      })
    );
  });

  // Regression test for the nested-modal freeze: the AlertDialog confirm
  // inside the delete-user Dialog must close cleanly and dispatch the DELETE.
  // With duplicate @radix-ui/react-focus-scope copies installed (Dialog and
  // AlertDialog on different versions), the two focus traps never see each
  // other's scope stack and fight over focus forever on close — stack
  // overflow in jsdom, a frozen tab in the browser, and the request never
  // sent. Pinned to one copy via the pnpm-workspace.yaml override.
  it("deletes the blocking guild from the confirm dialog and advances", async () => {
    const user = userEvent.setup();
    renderWithProviders(
      <AdminDeleteUserDialog
        open={true}
        onOpenChange={vi.fn()}
        onSuccess={vi.fn()}
        targetUser={targetUser}
      />,
      { auth: { user: buildUser({ role: "owner" }) } }
    );

    // Step 1 → Next runs the eligibility check and lands on resolve-blockers.
    await user.click(await screen.findByRole("button", { name: /next/i }));
    expect(await screen.findByText(/Lone Guild/)).toBeInTheDocument();

    // Open the confirm dialog and confirm the guild deletion.
    await user.click(screen.getByRole("button", { name: /delete guild/i }));
    const confirmDialog = await screen.findByRole("alertdialog");
    await user.click(within(confirmDialog).getByRole("button", { name: /delete guild/i }));

    // The DELETE must be sent, scoped to the blocked user.
    await waitFor(() => expect(deleteGuildSpy).toHaveBeenCalledWith("42"));

    // The confirm dialog closes and the refreshed (now clear) eligibility
    // advances the flow — nothing freezes or sticks around.
    await waitFor(() => {
      expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    });

    // The outer delete-user dialog must survive the confirm click. With
    // duplicated @radix-ui/react-dismissable-layer copies, the outer dialog's
    // layer registry can't see the AlertDialog's layer, treats the click as an
    // outside interaction, and dismisses everything (leaving body
    // pointer-events stuck at "none" — the frozen page).
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });
});
