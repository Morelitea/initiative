import type {
  InitiativeDirectoryEntry,
  InitiativeJoinRequestRead,
  InitiativeMemberRead,
  InitiativeRead,
} from "@/api/generated/initiativeAPI.schemas";

import { buildUserPublic, buildUserSummary } from "./user.factory";

let counter = 0;

export function resetCounter(): void {
  counter = 0;
}

export function buildInitiativeMember(
  overrides: Partial<InitiativeMemberRead> = {}
): InitiativeMemberRead {
  counter++;
  return {
    user: buildUserPublic(),
    role_id: null,
    role_name: null,
    role_display_name: null,
    is_manager: false,
    oidc_managed: false,
    joined_at: "2026-01-15T00:00:00.000Z",
    can_view_documents: true,
    can_view_projects: true,
    can_create_documents: false,
    can_create_projects: false,
    ...overrides,
  };
}

export function buildInitiative(overrides: Partial<InitiativeRead> = {}): InitiativeRead {
  counter++;
  return {
    id: counter,
    guild_id: 1,
    name: `Initiative ${counter}`,
    description: `Description for initiative ${counter}`,
    color: "#3b82f6",
    is_default: false,
    is_archived: false,
    // Fail-closed, like the column default: an initiative is invite-only until
    // someone opens it.
    join_policy: "private",
    auto_join: false,
    created_at: "2026-01-15T00:00:00.000Z",
    updated_at: "2026-01-15T00:00:00.000Z",
    members: [],
    ...overrides,
  };
}

/** One card in the guild's initiative directory (`GET /initiatives/directory`). */
export function buildInitiativeDirectoryEntry(
  overrides: Partial<InitiativeDirectoryEntry> = {}
): InitiativeDirectoryEntry {
  counter++;
  return {
    id: counter,
    name: `Initiative ${counter}`,
    description: `Description for initiative ${counter}`,
    color: "#3b82f6",
    join_policy: "open",
    member_count: 3,
    is_member: false,
    has_pending_request: false,
    // Reads zero for anyone who couldn't answer the queue anyway.
    pending_join_request_count: 0,
    ...overrides,
  };
}

/** One row of an initiative's join-request queue. Pending and never denied
 *  before — the plain knock a manager sees most of the time. */
export function buildInitiativeJoinRequest(
  overrides: Partial<InitiativeJoinRequestRead> = {}
): InitiativeJoinRequestRead {
  counter++;
  return {
    id: counter,
    initiative_id: 1,
    user: buildUserSummary(),
    status: "pending",
    message: null,
    created_at: "2026-01-15T00:00:00.000Z",
    resolved_at: null,
    resolved_by: null,
    prior_denials: 0,
    ...overrides,
  };
}
