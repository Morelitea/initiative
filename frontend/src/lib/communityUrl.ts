import { useCallback } from "react";

import { useCommunities } from "@/hooks/useCommunities";

// These build `/c/{id}` paths but are named for the community, like the rest of the
// code — see the NAMING note in `@/api/query-keys`.

/**
 * Create a community-scoped URL path.
 * @param communityId The community ID to scope to
 * @param path The sub-path within the community (e.g., "/projects" or "projects/47")
 * @returns The full community-scoped path (e.g., "/c/5/projects/47")
 */
export function communityPath(communityId: number, path: string): string {
  const normalized = path.startsWith("/") ? path : `/${path}`;
  return `/c/${communityId}${normalized}`;
}

/**
 * Hook that returns a function to create community-scoped URL paths
 * using the current active community from context.
 *
 * @returns A function that takes a sub-path and returns the full community-scoped path
 */
export function useCommunityPath() {
  const { activeCommunityId } = useCommunities();

  return useCallback(
    (path: string): string => {
      if (!activeCommunityId) {
        // Fall back to returning the path as-is if no community is active
        return path.startsWith("/") ? path : `/${path}`;
      }
      return communityPath(activeCommunityId, path);
    },
    [activeCommunityId]
  );
}

/**
 * Check if a path is a community-scoped path.
 * @param path The path to check
 * @returns True if the path starts with /c/:communityId/
 */
export function isCommunityScopedPath(path: string): boolean {
  return /^\/c\/\d+\//.test(path);
}

/**
 * The community a community-scoped path names, or null when it names none.
 * @param path The path to read (e.g. "/c/5/projects/47")
 */
export function communityIdFromPath(path: string): number | null {
  const match = path.match(/^\/c\/(\d+)(?:\/|$)/);
  return match ? Number(match[1]) : null;
}

/**
 * Whether a path is a community's billing forwarder (`/c/5/billing`, with or
 * without its query). The forwarder asks the server for the handoff itself, so
 * it is reached without the community being in the account's list: a
 * community on hold is missing from it, and its seat still needs the way to
 * its plan.
 */
export function isBillingForwardPath(path: string): boolean {
  const pathname = path.split("?")[0].split("#")[0];
  return communityIdFromPath(pathname) !== null && extractSubPath(pathname) === "/billing";
}

/**
 * Extract the sub-path from a community-scoped path (everything after /c/:communityId).
 * @param path The full path
 * @returns The sub-path (e.g., "/projects/47" from "/c/5/projects/47")
 */
export function extractSubPath(path: string): string {
  const match = path.match(/^\/c\/\d+(.*)$/);
  return match ? match[1] || "/" : path;
}

/**
 * Rewrite a community-scoped path so it names `initiativeId` as the initiative its
 * entity lives in.
 *
 * Three shapes, because the initiative segment may need replacing, removing, or
 * inserting: a path already under `/i/{other}`, a community-level path for an
 * entity that does belong to an initiative, and the reverse — an initiative
 * path for an entity that belongs to none (a plug-in's calendar).
 *
 * Returns the path unchanged when it isn't community-scoped, so a caller can
 * compare the result to decide whether anything needs correcting.
 */
export function canonicalInitiativePath(pathname: string, initiativeId: number | null): string {
  const community = pathname.match(/^\/c\/(\d+)(\/.*)?$/);
  if (!community) return pathname;
  const [, communityId, rest = ""] = community;
  const withoutInitiative = rest.replace(/^\/i\/\d+/, "");
  const prefix = initiativeId === null ? "" : `/i/${initiativeId}`;
  return `/c/${communityId}${prefix}${withoutInitiative}`;
}
