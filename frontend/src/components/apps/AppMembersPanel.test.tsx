/**
 * The seat's view of each member's answers to an app asking to act as them.
 *
 * One row per member, listing every request they were asked and where it
 * stands. The admin can end a member's answers, or everybody's, and has no
 * control that gives one.
 */

import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderPage } from "@/__tests__/helpers/render";
import {
  ConsentAccess,
  ConsentStatus,
  type GuildAppMemberConsent,
} from "@/api/generated/initiativeAPI.schemas";

import { AppMembersPanel } from "./AppMembersPanel";

const revokeMember = vi.fn();
const revokeAll = vi.fn();
let consents: GuildAppMemberConsent[] = [];

vi.mock("@/hooks/useGuildAppDetail", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/hooks/useGuildAppDetail")>()),
  useGuildAppMembers: () => ({
    isLoading: false,
    data: { summary: [], items: [], consents },
  }),
  useRevokeAllConnections: () => ({ mutate: vi.fn(), isPending: false }),
  useRevokeMemberConsents: () => ({ mutate: revokeMember, isPending: false }),
  useRevokeAllConsents: () => ({ mutate: revokeAll, isPending: false }),
}));

vi.mock("@/hooks/useUsers", () => ({
  useUsers: () => ({
    data: [
      { id: 5, full_name: "Ada" },
      { id: 6, full_name: "Grace" },
    ],
  }),
}));

const consent = (overrides: Partial<GuildAppMemberConsent> = {}): GuildAppMemberConsent => ({
  id: 1,
  user_id: 5,
  purpose: "node-1",
  label: "Comment on the linked issue",
  initiative_id: null,
  requested_access: ConsentAccess.read,
  granted_access: ConsentAccess.read,
  status: ConsentStatus.granted,
  requested_at: "2026-09-24T00:00:00Z",
  granted_at: "2026-09-24T01:00:00Z",
  revoked_at: null,
  ...overrides,
});

const rowFor = async (name: string) => {
  const row = (await screen.findByText(name)).closest("tr");
  if (!row) throw new Error(`no row for ${name}`);
  return within(row);
};

beforeEach(() => {
  revokeMember.mockReset();
  revokeAll.mockReset();
});

describe("AppMembersPanel consents", () => {
  it("groups each member's answers on one row", async () => {
    consents = [
      consent({ id: 1, purpose: null, label: "Anything" }),
      consent({ id: 2 }),
      consent({
        id: 3,
        user_id: 6,
        granted_access: null,
        granted_at: null,
        status: ConsentStatus.pending,
      }),
    ];
    renderPage(() => <AppMembersPanel appId={3} enabled />);

    const ada = await rowFor("Ada");
    expect(ada.getByText("Anything it does")).toBeInTheDocument();
    expect(ada.getByText("Comment on the linked issue")).toBeInTheDocument();
    expect(ada.getAllByText("Can read as you")).toHaveLength(2);

    const grace = await rowFor("Grace");
    expect(grace.getByText("Waiting for you")).toBeInTheDocument();
    expect(screen.getByText("1 member allows this")).toBeInTheDocument();
  });

  it("ends one member's answers, and offers nothing for answers already ended", async () => {
    consents = [
      consent({ id: 1 }),
      consent({
        id: 2,
        user_id: 6,
        status: ConsentStatus.revoked,
        revoked_at: "2026-09-24T02:00:00Z",
      }),
    ];
    renderPage(() => <AppMembersPanel appId={3} enabled />);

    const grace = await rowFor("Grace");
    expect(grace.queryByRole("button", { name: "Revoke" })).toBeNull();

    fireEvent.click((await rowFor("Ada")).getByRole("button", { name: "Revoke" }));
    await waitFor(() => expect(revokeMember).toHaveBeenCalledWith(5, expect.anything()));
  });

  it("asks before ending everybody's", async () => {
    consents = [consent()];
    renderPage(() => <AppMembersPanel appId={3} enabled />);

    fireEvent.click(await screen.findByRole("button", { name: "Stop it acting as anyone" }));
    expect(revokeAll).not.toHaveBeenCalled();
    const dialog = await screen.findByRole("alertdialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Stop it acting as anyone" }));
    await waitFor(() => expect(revokeAll).toHaveBeenCalled());
  });
});
