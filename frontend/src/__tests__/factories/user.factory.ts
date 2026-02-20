import type { UserPublic, UserGuildMember } from "@/api/generated/initiativeAPI.schemas";
import type { User } from "@/types/api";

let counter = 0;

export function resetCounter(): void {
  counter = 0;
}

export function buildUserPublic(overrides: Partial<UserPublic> = {}): UserPublic {
  counter++;
  return {
    id: counter,
    email: `user-${counter}@example.com`,
    full_name: `User ${counter}`,
    avatar_base64: null,
    avatar_url: null,
    ...overrides,
  };
}

export function buildUser(overrides: Partial<User> = {}): User {
  counter++;
  return {
    id: counter,
    email: `user-${counter}@example.com`,
    full_name: `User ${counter}`,
    avatar_base64: null,
    avatar_url: null,
    role: "member",
    can_create_guilds: true,
    is_active: true,
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
    avatar_base64: null,
    avatar_url: null,
    role: "member",
    guild_role: "member",
    oidc_managed: false,
    is_active: true,
    email_verified: true,
    created_at: "2026-01-15T00:00:00.000Z",
    initiative_roles: [],
    ...overrides,
  };
}
