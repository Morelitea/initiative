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
  auditRead: "audit.read",
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

/** Capabilities behind the **Admin dashboard** area (operational: platform
 * users + time-bound access grants). */
const ADMIN_DASHBOARD_CAPABILITIES: Capability[] = [
  Capability.usersRead,
  Capability.usersAgeUnblock,
  Capability.usersManage,
  Capability.guildsManage,
  Capability.announcementsManage,
  Capability.contentModerate,
  Capability.auditRead,
  Capability.accessRequest,
  Capability.accessApprove,
  Capability.accessRead,
];

/** True iff the user can configure the platform (Platform settings area). */
export function canManagePlatformConfig(user: WithCapabilities): boolean {
  return hasAnyCapability(user, PLATFORM_SETTINGS_CAPABILITIES);
}

/** True iff the user can reach the operational Admin dashboard area. */
export function canAccessAdminDashboard(user: WithCapabilities): boolean {
  return hasAnyCapability(user, ADMIN_DASHBOARD_CAPABILITIES);
}

/** True iff the user can access *either* platform area — used for coarse
 * gating (no-guild layout choice, route guards). */
export function canAccessPlatformAdmin(user: WithCapabilities): boolean {
  return canManagePlatformConfig(user) || canAccessAdminDashboard(user);
}

/** True when a server-computed per-resource permission level allows writing.
 * Reads `my_permission_level` — never derive this client-side. */
export const hasWriteAccess = (level: string | null | undefined): boolean =>
  level === "owner" || level === "write";
