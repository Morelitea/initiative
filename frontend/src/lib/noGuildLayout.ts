/**
 * Pure decision helper for the layout `_authenticated.tsx` should
 * render when the current user has zero guild memberships.
 *
 * Extracted from the route component so the path-based exemption
 * rules are unit-testable without a full router + provider setup —
 * the routing gate is an auth boundary, and CLAUDE.md asks for
 * Vitest coverage on auth.
 *
 * Outcomes:
 * - ``"main"``  — user has at least one guild; render the standard
 *                 sidebar layout.
 * - ``"shell"`` — no guilds, but the current path is one that works
 *                 without guild context: a user-scoped settings route,
 *                 a platform-admin settings route for an admin, or the
 *                 community directory. Render the chromeless
 *                 ``NoGuildSettingsShell`` so the user can still reach
 *                 Danger Zone / platform configuration — or join a guild
 *                 without waiting for an invite.
 * - ``"empty"`` — no guilds and no exempt path; show
 *                 ``NoGuildState`` (the create / join / logout
 *                 landing page).
 *
 * The ``isPlatformAdmin`` flag matches the coarse ``canAccessPlatformAdmin``
 * predicate (can reach *either* the Admin dashboard or Platform settings).
 * Keeping the checks aligned guarantees the no-guild shell never admits
 * anyone who couldn't already reach the page in the normal sidebar layout.
 */
export type NoGuildLayoutChoice = "main" | "shell" | "empty";

export interface NoGuildLayoutInputs {
  hasGuilds: boolean;
  pathname: string;
  isPlatformAdmin: boolean;
}

const isUserSettingsPath = (path: string): boolean =>
  path === "/profile" || path.startsWith("/profile/");

// The community directory is how someone with no memberships joins a guild
// without an invite, so it has to survive the empty state rather than being
// replaced by it.
const isCommunityPath = (path: string): boolean =>
  path === "/communities" || path.startsWith("/communities/");

// Both platform areas: the Admin dashboard (/settings/admin) and Platform
// settings (/settings/platform). A guild-less platform user must still reach
// either via the chromeless shell.
const isAdminSettingsPath = (path: string): boolean =>
  path === "/settings/admin" ||
  path.startsWith("/settings/admin/") ||
  path === "/settings/platform" ||
  path.startsWith("/settings/platform/");

export function chooseNoGuildLayout({
  hasGuilds,
  pathname,
  isPlatformAdmin,
}: NoGuildLayoutInputs): NoGuildLayoutChoice {
  if (hasGuilds) return "main";
  if (isUserSettingsPath(pathname)) return "shell";
  if (isCommunityPath(pathname)) return "shell";
  if (isAdminSettingsPath(pathname) && isPlatformAdmin) return "shell";
  return "empty";
}
