/**
 * Platform capability helpers (frontend mirror of `app.core.capabilities`).
 *
 * The backend computes the authoritative capability set for the current user
 * and ships it on `UserRead.capabilities`. The frontend never derives
 * capabilities from the role itself — it only reads the list — so the two
 * stay in lockstep. These string constants must match the backend
 * `Capability` enum values exactly.
 */

import type { UserRead } from "@/api/generated/initiativeAPI.schemas";

export const Capability = {
  usersRead: "users.read",
  usersAgeUnblock: "users.age_unblock",
  usersManage: "users.manage",
  usersDelete: "users.delete",
  rolesAssign: "roles.assign",
  guildsRead: "guilds.read",
  guildsManage: "guilds.manage",
  announcementsManage: "announcements.manage",
  contentModerate: "content.moderate",
  dataBypass: "data.bypass",
  accessRequest: "access.request",
  accessApprove: "access.approve",
  accessRead: "access.read",
  configManage: "config.manage",
  appsManage: "apps.manage",
} as const;

export type Capability = (typeof Capability)[keyof typeof Capability];

/** A minimal shape so callers can pass the auth user (or any object with a
 * capabilities list) without importing the full `UserRead`. */
type WithCapabilities = Pick<UserRead, "capabilities"> | null | undefined;

/** True iff the user's standing role grants `capability`. */
export function hasCapability(user: WithCapabilities, capability: Capability): boolean {
  return user?.capabilities?.includes(capability) ?? false;
}

/** True iff the user holds at least one of the given capabilities. */
export function hasAnyCapability(user: WithCapabilities, capabilities: Capability[]): boolean {
  return capabilities.some((c) => hasCapability(user, c));
}

/** Capabilities behind the **Platform settings** area (app-wide config:
 * auth, branding, email, AI, app services). Owner-only in practice. */
const PLATFORM_SETTINGS_CAPABILITIES: Capability[] = [
  Capability.configManage,
  Capability.appsManage,
];

/** Capabilities behind the **Operator dashboard** area (operational: platform
 * users + time-bound access grants). */
const OPERATOR_DASHBOARD_CAPABILITIES: Capability[] = [
  Capability.usersRead,
  Capability.usersAgeUnblock,
  Capability.usersManage,
  Capability.guildsManage,
  Capability.announcementsManage,
  Capability.contentModerate,
  Capability.accessRequest,
  Capability.accessApprove,
  Capability.accessRead,
];

/** True iff the user can configure the platform (Platform settings area). */
export function canManagePlatformConfig(user: WithCapabilities): boolean {
  return hasAnyCapability(user, PLATFORM_SETTINGS_CAPABILITIES);
}

/** True iff the user can reach the operational Operator dashboard area. */
export function canAccessOperatorDashboard(user: WithCapabilities): boolean {
  return hasAnyCapability(user, OPERATOR_DASHBOARD_CAPABILITIES);
}

/** True iff the user can access *either* platform area — used for coarse
 * gating (no-guild layout choice, route guards). */
export function canAccessPlatformAdmin(user: WithCapabilities): boolean {
  return canManagePlatformConfig(user) || canAccessOperatorDashboard(user);
}

/** True when a server-computed per-resource permission level allows writing.
 * Reads `my_permission_level` — never derive this client-side. */
/**
 * Whether this request holds the community's top seat.
 *
 * The seat owns what a community is billed for, how people get into it, and
 * what it hands to anyone outside it — so every affordance leading to the
 * billing portal, the Authentication tab, AI or apps asks this, and an
 * ordinary admin is not shown a button the server refuses.
 *
 * Two ways to hold it: the membership row, or a live settings grant at the
 * superadmin rung, which is the seat lent to somebody for a window. Mirrors
 * the backend's ``public.guild_superadmin``, which is what actually decides.
 */
export const holdsGuildSeat = (
  guild: { role?: string | null; grantSettingsLevel?: string | null } | null | undefined
): boolean => guild?.role === "superadmin" || guild?.grantSettingsLevel === "superadmin";

export const hasWriteAccess = (level: string | null | undefined): boolean =>
  level === "owner" || level === "write";
