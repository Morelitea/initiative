/**
 * The transfer dialog offers the community's admins, and beside them the
 * installed apps the server says may own everything that moves.
 */
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildUserGuildMember } from "@/__tests__/factories";
import { renderWithProviders } from "@/__tests__/helpers/render";
import type { OwnedContentResponse } from "@/api/generated/initiativeAPI.schemas";

const api = vi.hoisted(() => ({
  listOwned: vi.fn(),
  listUnowned: vi.fn(),
  transfer: vi.fn(),
  claim: vi.fn(),
}));

vi.mock("@/api/generated/users/users", () => ({
  listOwnedContentApiV1GGuildIdUsersUserIdOwnedContentGet: api.listOwned,
  listUnownedContentApiV1GGuildIdUsersUnownedContentGet: api.listUnowned,
  transferOwnershipApiV1GGuildIdUsersUserIdTransferOwnershipPost: api.transfer,
  claimUnownedContentApiV1GGuildIdUsersUnownedContentClaimPost: api.claim,
}));

vi.mock("@/hooks/useActiveGuildId", () => ({ useActiveGuildId: () => 7 }));

import { TransferContentOwnershipDialog } from "./TransferContentOwnershipDialog";

const admin = buildUserGuildMember({ id: 11, full_name: "Ada Admin" });
const member = buildUserGuildMember({ id: 12, full_name: "Mel Member" });

const content = (overrides: Partial<OwnedContentResponse> = {}): OwnedContentResponse => ({
  items: [{ tool: "project", id: 5, name: "Roadmap" }],
  counts: { project: 1 },
  total: 1,
  eligible_apps: [],
  ...overrides,
});

describe("TransferContentOwnershipDialog", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.transfer.mockResolvedValue({ counts: { project: 1 }, total: 1 });
    api.claim.mockResolvedValue({ counts: { project: 1 }, total: 1 });
  });

  it("offers an app the server lists and hands the content to it", async () => {
    api.listOwned.mockResolvedValue(
      content({ eligible_apps: [{ id: 301, name: "Automations", avatar_url: null }] })
    );

    renderWithProviders(
      <TransferContentOwnershipDialog
        open
        onOpenChange={vi.fn()}
        member={member}
        admins={[admin]}
      />
    );

    await userEvent.click(await screen.findByRole("combobox"));
    expect(await screen.findByRole("option", { name: "Ada Admin" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("option", { name: "Automations" }));
    await userEvent.click(screen.getByRole("button", { name: "Transfer" }));

    await waitFor(() =>
      expect(api.transfer).toHaveBeenCalledWith(7, member.id, { new_owner_app_id: 301 })
    );
  });

  it("offers only admins when no app may own it, and names a person by id", async () => {
    api.listUnowned.mockResolvedValue(content());

    renderWithProviders(
      <TransferContentOwnershipDialog
        open
        onOpenChange={vi.fn()}
        member={null}
        admins={[admin]}
        defaultRecipientId={admin.id}
      />
    );

    await userEvent.click(await screen.findByRole("combobox"));
    expect(await screen.findByRole("option", { name: "Ada Admin" })).toBeInTheDocument();
    expect(screen.queryByText("Apps")).not.toBeInTheDocument();
    await userEvent.keyboard("{Escape}");
    await userEvent.click(screen.getByRole("button", { name: "Transfer" }));

    await waitFor(() => expect(api.claim).toHaveBeenCalledWith(7, { new_owner_id: admin.id }));
  });
});
