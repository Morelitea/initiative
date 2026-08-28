import type {
  InitiativeDirectoryEntry,
  InitiativeMemberRead,
  InitiativeRead,
} from "@/api/generated/initiativeAPI.schemas";

import { buildUserPublic } from "./user.factory";

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
    ...overrides,
  };
}
