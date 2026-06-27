import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";

import { buildDocumentSummary } from "@/__tests__/factories/document.factory";
import { buildInitiative, buildInitiativeMember } from "@/__tests__/factories/initiative.factory";
import { buildUser, buildUserPublic } from "@/__tests__/factories/user.factory";
import { guildHttp } from "@/__tests__/helpers/guildHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderWithProviders } from "@/__tests__/helpers/render";
import type {
  DocumentSummary,
  InitiativeRoleRead,
  ResourceGrantSchema,
} from "@/api/generated/initiativeAPI.schemas";

import { BulkEditAccessDialog } from "./BulkEditAccessDialog";

// ── Fixtures ─────────────────────────────────────────────────────────────────
// One initiative (id 50) with a single non-current member (Bob, id 101) and one
// editor role (id 200). The current user is id 1, so Bob is selectable and Bob
// won't be filtered out as "self".

const INITIATIVE_ID = 50;
const BOB_ID = 101;
const EDITOR_ROLE_ID = 200;

const bob = buildUserPublic({ id: BOB_ID, full_name: "Bob Builder", email: "bob@example.com" });

const initiative = buildInitiative({
  id: INITIATIVE_ID,
  name: "Init",
  members: [buildInitiativeMember({ user: bob, role_id: EDITOR_ROLE_ID })],
});

const roles: InitiativeRoleRead[] = [
  {
    id: EDITOR_ROLE_ID,
    name: "editor",
    display_name: "Editor",
    is_builtin: false,
    is_manager: false,
    position: 0,
    permissions: {},
    member_count: 1,
  },
];

/**
 * A document currently shared with *all initiative members* (Viewer). This is
 * the state that triggered the defect: a bulk per-user/per-role grant must drop
 * the all-members grant so ShareControl's two-mode model can still render it.
 */
function allMembersDoc(extraGrants: ResourceGrantSchema[] = []): DocumentSummary {
  return buildDocumentSummary({
    id: 10,
    initiative_id: INITIATIVE_ID,
    my_permission_level: "owner",
    grants: [
      { all_initiative_members: true, level: "read" },
      { user_id: 999, level: "owner" },
      ...extraGrants,
    ],
  });
}

/**
 * A document that is NOT shared with all initiative members — only an owner and
 * one individual grant. Removing all-members access on this doc is a no-op.
 */
function restrictedDoc(id: number): DocumentSummary {
  return buildDocumentSummary({
    id,
    initiative_id: INITIATIVE_ID,
    my_permission_level: "owner",
    grants: [
      { user_id: 999, level: "owner" },
      { user_id: BOB_ID, level: "read" },
    ],
  });
}

/** Capture the PUT /grants payloads crossing the network boundary. */
function captureGrantPuts() {
  const captured: ResourceGrantSchema[][] = [];
  server.use(
    guildHttp.get("/initiatives/", () => HttpResponse.json([initiative])),
    guildHttp.get("/initiatives/:initiativeId/roles", () => HttpResponse.json(roles)),
    guildHttp.put("/documents/:documentId/grants", async ({ request }) => {
      captured.push((await request.json()) as ResourceGrantSchema[]);
      return HttpResponse.json({});
    })
  );
  return captured;
}

function renderDialog(documents: DocumentSummary[]) {
  return renderWithProviders(
    <BulkEditAccessDialog open onOpenChange={vi.fn()} onSuccess={vi.fn()} documents={documents} />,
    { auth: { user: buildUser({ id: 1 }) } }
  );
}

describe("BulkEditAccessDialog grant rebuild", () => {
  it("user grant drops the all-members grant (switches the doc to restricted mode)", async () => {
    const user = userEvent.setup();
    const captured = captureGrantPuts();

    renderDialog([allMembersDoc()]);

    // People is the default tab.
    // Open the picker via its placeholder text (its accessible *name* is the
    // "People" label, which collides with the tab — match the visible text).
    await user.click(screen.getByText("Select people…"));
    await user.click(await screen.findByText("Bob Builder"));
    await user.click(screen.getByRole("button", { name: /Grant 1 person/i }));

    await waitFor(() => expect(captured).toHaveLength(1));
    const payload = captured[0];
    // The all-members grant must be gone — otherwise ShareControl gets a mixed
    // list it can't display and silently discards on the next save.
    expect(payload.some((g) => g.all_initiative_members)).toBe(false);
    // The targeted user is granted at the chosen level.
    expect(payload).toContainEqual({ user_id: BOB_ID, level: "read" });
    // Owner grants are dropped from the payload (the server re-adds the owner).
    expect(payload.some((g) => g.level === "owner")).toBe(false);
  });

  it("role grant drops the all-members grant (switches the doc to restricted mode)", async () => {
    const user = userEvent.setup();
    const captured = captureGrantPuts();

    renderDialog([allMembersDoc()]);

    await user.click(screen.getByRole("tab", { name: "Roles" }));
    // Open the picker via its placeholder text.
    await user.click(screen.getByText("Select roles…"));
    await user.click(await screen.findByText("Editor"));
    await user.click(screen.getByRole("button", { name: /Grant 1 role/i }));

    await waitFor(() => expect(captured).toHaveLength(1));
    const payload = captured[0];
    expect(payload.some((g) => g.all_initiative_members)).toBe(false);
    expect(payload).toContainEqual({ role_id: EDITOR_ROLE_ID, level: "read" });
  });

  it("user revoke keeps the all-members grant, dropping only the targeted user", async () => {
    const user = userEvent.setup();
    const captured = captureGrantPuts();

    // Doc shared with all members AND with Bob individually.
    renderDialog([allMembersDoc([{ user_id: BOB_ID, level: "read" }])]);

    // People is the default tab.
    // Switch the action mode from Grant to Revoke (the mode select is labelled
    // "Action"; click the trigger, not the pointer-events:none value span).
    await user.click(screen.getByLabelText("Action"));
    await user.click(await screen.findByRole("option", { name: "Revoke access" }));
    await user.click(screen.getByText("Select people to revoke…"));
    // Bob has no resolvable name in revoke mode (doc.initiative is null), so the
    // picker falls back to "User <id>".
    await user.click(await screen.findByText(`User ${BOB_ID}`));
    await user.click(screen.getByRole("button", { name: /Revoke 1 person/i }));

    await waitFor(() => expect(captured).toHaveLength(1));
    const payload = captured[0];
    // Revoking one grantee must NOT silently strip everyone's all-members share.
    expect(payload.some((g) => g.all_initiative_members)).toBe(true);
    expect(payload.some((g) => g.user_id === BOB_ID)).toBe(false);
  });

  it("all-members remove only writes docs that actually have an all-members grant", async () => {
    const user = userEvent.setup();
    const captured = captureGrantPuts();

    // One doc shared with all members (id 10), one restricted-only (id 11).
    renderDialog([allMembersDoc(), restrictedDoc(11)]);

    await user.click(screen.getByRole("tab", { name: "All members" }));
    await user.click(screen.getByLabelText("Action"));
    await user.click(await screen.findByRole("option", { name: "Remove all-members access" }));
    await user.click(screen.getByRole("button", { name: "Remove all-members access" }));

    // Exactly one PUT: the restricted-only doc is skipped (no-op), not re-saved
    // with an unchanged grant list.
    await waitFor(() => expect(captured).toHaveLength(1));
    expect(captured[0].some((g) => g.all_initiative_members)).toBe(false);
  });

  it("all-members remove makes no request when nothing is shared with all members", async () => {
    const user = userEvent.setup();
    const captured = captureGrantPuts();
    const onSuccess = vi.fn();

    renderWithProviders(
      <BulkEditAccessDialog
        open
        onOpenChange={vi.fn()}
        onSuccess={onSuccess}
        documents={[restrictedDoc(11)]}
      />,
      { auth: { user: buildUser({ id: 1 }) } }
    );

    await user.click(screen.getByRole("tab", { name: "All members" }));
    await user.click(screen.getByLabelText("Action"));
    await user.click(await screen.findByRole("option", { name: "Remove all-members access" }));
    await user.click(screen.getByRole("button", { name: "Remove all-members access" }));

    // The handler still settles (dialog closes) but issues zero writes.
    await waitFor(() => expect(onSuccess).toHaveBeenCalled());
    expect(captured).toHaveLength(0);
  });
});
