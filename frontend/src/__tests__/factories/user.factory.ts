import type {
  OwnedDecoration,
  UserGuildMember,
  UserProfile,
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
    username: `user-${counter}`,
    discriminator: 1000 + counter,
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
    username: `user-${counter}`,
    discriminator: 1000 + counter,
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
    username: `user-${counter}`,
    discriminator: 1000 + counter,
    username_chosen: true,
    // Answered, like the handle: a test that is not about the age gate should
    // never meet it. The gate's own tests override these two.
    age_confirmed_at: "2026-01-01T00:00:00Z",
    age_confirmation_required: false,
    full_name: `User ${counter}`,
    avatar_url: null,
    role: "member",
    capabilities: capabilitiesForRole(role),
    can_create_guilds: true,
    status: "active",
    email_verified: true,
    created_at: "2026-01-15T00:00:00.000Z",
    updated_at: "2026-01-15T00:00:00.000Z",
    custom_status: { emoji: null, text: null },
    profile_decorations: { banner: null, frame: null, trophies: [] },
    week_starts_on: 0,
    timezone: "America/New_York",
    ...overrides,
  };
}

export function buildUserGuildMember(overrides: Partial<UserGuildMember> = {}): UserGuildMember {
  counter++;
  return {
    id: counter,
    username: `user-${counter}`,
    discriminator: 1000 + counter,
    full_name: `User ${counter}`,
    avatar_url: null,
    guild_role: "member",
    oidc_managed: false,
    status: "active",
    created_at: "2026-01-15T00:00:00.000Z",
    initiative_roles: [],
    ...overrides,
  };
}

/** A member's profile, as the rest of their guild sees them. Bare by default —
 *  no status and nothing worn — so a test that asserts on a decoration has to
 *  have put it there. */
export function buildUserProfile(overrides: Partial<UserProfile> = {}): UserProfile {
  counter++;
  return {
    id: counter,
    username: `user-${counter}`,
    discriminator: 1000 + counter,
    avatar_url: null,
    status: "active",
    custom_status: { emoji: null, text: null },
    profile_decorations: { banner: null, frame: null, trophies: [] },
    presence: "offline",
    joined_at: "2026-01-15T00:00:00.000Z",
    ...overrides,
  };
}

/** One decoration in somebody's library. Shipped (no pack) by default. */
export function buildOwnedDecoration(overrides: Partial<OwnedDecoration> = {}): OwnedDecoration {
  return { id: "core.aurora", kind: "banner", source: null, ...overrides };
}
