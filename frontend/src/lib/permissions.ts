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

/**
 * The community's ladder, lowest rung first — the one ordering, mirroring
 * `GUILD_LADDER` on the backend. `support` is the identity granted access
 * carries and sits below a member: it is not a rung of the community.
 */
export const GUILD_LADDER = ["support", "member", "admin", "superadmin"] as const;

/**
 * Whether the rung `held` carries what `rung` carries.
 *
 * The ladder asked as a comparison rather than as a flag per question.
 * Mirrors `GuildRole.reaches` on the backend, which is what actually decides;
 * a rung the server has not sent, or one this build does not know, reaches
 * nothing.
 */
export const rungReaches = (
  held: string | null | undefined,
  rung: (typeof GUILD_LADDER)[number]
): boolean => {
  const at = GUILD_LADDER.indexOf(held as (typeof GUILD_LADDER)[number]);
  return at >= 0 && at >= GUILD_LADDER.indexOf(rung);
};

/** True when a server-computed per-resource permission level allows writing.
 * Reads `my_permission_level` — never derive this client-side. */
/**
 * Whether this request holds the community's top seat.
 *
 * The seat owns what a community is billed for, how people get into it, what
 * it hands to anyone outside it, and what takes it out in one file — so every
 * affordance leading to the billing portal, the Authentication tab, AI, apps,
 * Data or the danger zone asks this, and an ordinary admin is not shown a
 * button the server refuses.
 *
 * The seat is the community's top rung, so this reads the rung rather than a
 * flag of its own: `GuildRead.role` is what the caller holds here — the
 * membership row's rung, or the one a live settings grant lends for its
 * window. The same rule `public.guild_superadmin` applies in the database.
 */
export const holdsGuildSeat = (guild: { role?: string | null } | null | undefined): boolean =>
  rungReaches(guild?.role, "superadmin");

/**
 * Whether this request administers the community's own configuration.
 *
 * Its settings, its roster and its invites, as distinct from the work inside
 * it. The rung the server sent reaching `admin` — on a membership row and on
 * a live settings grant alike, since the lower of the grant's two rungs is
 * "what a guild admin administers".
 *
 * Not the same question as reaching the community's content: a settings grant
 * carries none. Use {@link administersGuildContent} where the surface is built
 * on the work rather than on the configuration.
 */
export const administersGuild = (guild: { role?: string | null } | null | undefined): boolean =>
  rungReaches(guild?.role, "admin");

/**
 * Whether this request reaches the community's content at all.
 *
 * A member does. Somebody reaching the community by a content grant does. A
 * settings-only grant does not — the server refuses every `/g/{id}` content
 * route for one — so the surfaces built on content are not offered with it.
 */
export const reachesGuildContent = (
  guild: { reachesContent?: boolean } | null | undefined
): boolean => guild?.reachesContent !== false;

/**
 * Whether this request administers the community's *work*.
 *
 * Both halves: the rung reaches `admin`, and this entry reaches content at
 * all. A settings grant runs a community's configuration and none of what is
 * inside it, so the surfaces built on the work ask this one.
 */
export const administersGuildContent = (
  guild: { role?: string | null; reachesContent?: boolean } | null | undefined
): boolean => administersGuild(guild) && reachesGuildContent(guild);

/**
 * Whether this request may change the community configuration it reaches.
 *
 * The server's answer (`GuildRead.can_write_settings`), the same rule the
 * settings routes refuse a change by: the membership row's administrator
 * does, and a settings grant does beside a read/write grant. A rung that
 * reaches the settings without it reads them.
 */
export const changesGuildSettings = (
  guild: { can_write_settings?: boolean } | null | undefined
): boolean => guild?.can_write_settings === true;

export const hasWriteAccess = (level: string | null | undefined): boolean =>
  level === "owner" || level === "write";
