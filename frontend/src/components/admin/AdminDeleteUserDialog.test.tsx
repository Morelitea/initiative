import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildUser } from "@/__tests__/factories";
import { server } from "@/__tests__/helpers/msw-server";
import { renderWithProviders } from "@/__tests__/helpers/render";
import type { AdminUserRead } from "@/api/generated/initiativeAPI.schemas";

import { AdminDeleteUserDialog } from "./AdminDeleteUserDialog";

const targetUser: AdminUserRead = {
  ...buildUser({ id: 42, status: "active" }),
  email: "sole-admin@example.com",
  purge_at: null,
};

const eligibilityWithGuildBlocker = {
  can_delete: false,
  blockers: ["Only superadmin of community Lone Community"],
  warnings: [],
  owned_projects: [],
  guild_blockers: [{ guild_id: 77, guild_name: "Lone Community" }],
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

describe("AdminDeleteUserDialog community blocker resolution", () => {
  beforeEach(() => {
    let eligibilityCalls = 0;
    server.use(
      http.get("/api/v1/operator/users/42/deletion-eligibility", () => {
        eligibilityCalls += 1;
        // First check: blocked by the community. Once the seat is resolved
        // inside the community, checking again comes back clear.
        return HttpResponse.json(
          eligibilityCalls === 1 ? eligibilityWithGuildBlocker : eligibilityClear
        );
      })
    );
  });

  it("sends the operator into the community and checks again", async () => {
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
    expect(await screen.findByText(/Lone Community/)).toBeInTheDocument();

    // The seat is resolved inside the community, under break-glass; the
    // dialog says so and offers nothing that acts on the community itself.
    expect(screen.getByText(/break glass into the community/i)).toBeInTheDocument();
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /delete community/i })).not.toBeInTheDocument();

    // Checking again picks up the resolved blocker and moves on to confirm.
    await user.click(screen.getByRole("button", { name: /check again/i }));
    await waitFor(() =>
      expect(screen.queryByRole("button", { name: /check again/i })).not.toBeInTheDocument()
    );
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });
});
