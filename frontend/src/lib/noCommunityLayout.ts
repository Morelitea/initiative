/**
 * Pure decision helper for the layout `_authenticated.tsx` should
 * render when the current user has zero community memberships.
 *
 * Extracted from the route component so the path-based exemption
 * rules are unit-testable without a full router + provider setup —
 * the routing gate is an auth boundary, and CLAUDE.md asks for
 * Vitest coverage on auth.
 *
 * Outcomes:
 * - ``"main"``  — user has at least one community; render the standard
 *                 sidebar layout.
 * - ``"shell"`` — no communities, but the current path is one that works
 *                 without community context: a user-scoped settings route,
 *                 a platform route for someone who can reach it, or the
 *                 community directory. Render the chromeless
 *                 ``NoCommunitySettingsShell`` so the user can still reach
 *                 Danger Zone / platform configuration — or join a community
 *                 without waiting for an invite, or reach the billing
 *                 portal for a community that is on hold.
 * - ``"empty"`` — no communities and no exempt path; show
 *                 ``NoCommunityState`` (the create / join / logout
 *                 landing page).
 *
 * The ``canAccessPlatformAreas`` flag is the coarse ``canAccessPlatformAreas``
 * predicate (can reach *either* the Operator dashboard or Platform settings).
 * Keeping the checks aligned guarantees the no-community shell never admits
 * anyone who couldn't already reach the page in the normal sidebar layout.
 */
import { isBillingForwardPath } from "@/lib/communityUrl";

export type NoCommunityLayoutChoice = "main" | "shell" | "empty";

export interface NoCommunityLayoutInputs {
  hasCommunities: boolean;
  pathname: string;
  canAccessPlatformAreas: boolean;
}

const isUserSettingsPath = (path: string): boolean =>
  path === "/profile" || path.startsWith("/profile/");

// The community directory is how someone with no memberships joins a community
// without an invite, so it has to survive the empty state rather than being
// replaced by it.
const isCommunityPath = (path: string): boolean =>
  path === "/communities" || path.startsWith("/communities/");

// Both platform areas: the Operator dashboard (/settings/operator) and Platform
// settings (/settings/platform). A community-less platform user must still reach
// either via the chromeless shell.
const isPlatformSettingsPath = (path: string): boolean =>
  path === "/settings/operator" ||
  path.startsWith("/settings/operator/") ||
  path === "/settings/platform" ||
  path.startsWith("/settings/platform/");

export function chooseNoCommunityLayout({
  hasCommunities,
  pathname,
  canAccessPlatformAreas,
}: NoCommunityLayoutInputs): NoCommunityLayoutChoice {
  if (hasCommunities) return "main";
  if (isUserSettingsPath(pathname)) return "shell";
  if (isCommunityPath(pathname)) return "shell";
  if (isBillingForwardPath(pathname)) return "shell";
  if (isPlatformSettingsPath(pathname) && canAccessPlatformAreas) return "shell";
  return "empty";
}
