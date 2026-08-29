import type {
  UserGuildMember,
  UserPublic,
  UserRead,
  UserRole,
  UserSummary,
} from "@/api/generated/initiativeAPI.schemas";

let counter = 0;

export function resetCounter(): void {
  counter = 0;
}

// Test-only mirror of the backend `app.core.capabilities` ladder, so a factory
// user built with `role: "owner"` lands the capabilities production would send.
// The backend (`UserRead.capabilities`) remains the single source of truth at
// runtime; this only fills the gap in synthetic fixtures.
const ROLE_CAPABILITIES: Record<UserRole, string[]> = {
  member: [],
  support: ["access.request", "audit.read", "guilds.read", "users.read"],
  moderator: [
    "access.request",
    "audit.read",
    "content.moderate",
    "guilds.read",
    "users.manage",
    "users.read",
  ],
  operator: [
    "access.approve",
    "access.read",
    "access.request",
    "audit.read",
    "content.moderate",
    "data.bypass",
    "guilds.manage",
    "guilds.read",
    "roles.assign",
    "users.delete",
    "users.manage",
    "users.read",
  ],
  owner: [
    "access.approve",
    "access.read",
    "apps.manage",
    "audit.read",
    "config.manage",
    "content.moderate",
    "data.bypass",
    "guilds.manage",
    "guilds.read",
    "roles.assign",
    "users.delete",
    "users.manage",
    "users.read",
  ],
};

export function capabilitiesForRole(role: UserRole): string[] {
  return ROLE_CAPABILITIES[role] ?? [];
}

export function buildUserPublic(overrides: Partial<UserPublic> = {}): UserPublic {
  counter++;
  return {
    id: counter,
    email: `user-${counter}@example.com`,
    full_name: `User ${counter}`,
    avatar_url: null,
    ...overrides,
  };
}

/** The slim projection the member search/typeahead endpoints return — no
 *  email, role, or timestamps. Use this for picker fixtures so a test can't
 *  pass on a field the real payload never carries. */
export function buildUserSummary(overrides: Partial<UserSummary> = {}): UserSummary {
  counter++;
  return {
    id: counter,
    full_name: `User ${counter}`,
    avatar_url: null,
    status: "active",
    ...overrides,
  };
}

export function buildUser(overrides: Partial<UserRead> = {}): UserRead {
  counter++;
  const role = overrides.role ?? "member";
  return {
    id: counter,
    email: `user-${counter}@example.com`,
    full_name: `User ${counter}`,
    avatar_url: null,
    role: "member",
    capabilities: capabilitiesForRole(role),
    can_create_guilds: true,
    status: "active",
    email_verified: true,
    created_at: "2026-01-15T00:00:00.000Z",
    updated_at: "2026-01-15T00:00:00.000Z",
    week_starts_on: 0,
    timezone: "America/New_York",
    ...overrides,
  };
}

export function buildUserGuildMember(overrides: Partial<UserGuildMember> = {}): UserGuildMember {
  counter++;
  return {
    id: counter,
    email: `user-${counter}@example.com`,
    full_name: `User ${counter}`,
    avatar_url: null,
    role: "member",
    guild_role: "member",
    oidc_managed: false,
    status: "active",
    email_verified: true,
    created_at: "2026-01-15T00:00:00.000Z",
    initiative_roles: [],
    ...overrides,
  };
}
