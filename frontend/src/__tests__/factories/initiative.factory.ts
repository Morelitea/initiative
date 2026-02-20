import type { InitiativeMemberRead } from "@/api/generated/initiativeAPI.schemas";
import type { Initiative } from "@/types/api";
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
    role: "member",
    role_id: null,
    role_name: null,
    role_display_name: null,
    is_manager: false,
    oidc_managed: false,
    joined_at: "2026-01-15T00:00:00.000Z",
    can_view_docs: true,
    can_view_projects: true,
    can_create_docs: false,
    can_create_projects: false,
    ...overrides,
  };
}

export function buildInitiative(overrides: Partial<Initiative> = {}): Initiative {
  counter++;
  return {
    id: counter,
    name: `Initiative ${counter}`,
    description: `Description for initiative ${counter}`,
    color: "#3b82f6",
    is_default: false,
    created_at: "2026-01-15T00:00:00.000Z",
    updated_at: "2026-01-15T00:00:00.000Z",
    members: [],
    ...overrides,
  };
}
