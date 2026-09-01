import { useCallback } from "react";

import { useGuilds } from "@/hooks/useGuilds";

// These build `/c/{id}` paths but are named for the guild, like the rest of the
// code — see the NAMING note in `@/api/query-keys`.

/**
 * Create a guild-scoped URL path.
 * @param guildId The guild ID to scope to
 * @param path The sub-path within the guild (e.g., "/projects" or "projects/47")
 * @returns The full guild-scoped path (e.g., "/c/5/projects/47")
 */
export function guildPath(guildId: number, path: string): string {
  const normalized = path.startsWith("/") ? path : `/${path}`;
  return `/c/${guildId}${normalized}`;
}

/**
 * Hook that returns a function to create guild-scoped URL paths
 * using the current active guild from context.
 *
 * @returns A function that takes a sub-path and returns the full guild-scoped path
 */
export function useGuildPath() {
  const { activeGuildId } = useGuilds();

  return useCallback(
    (path: string): string => {
      if (!activeGuildId) {
        // Fall back to returning the path as-is if no guild is active
        return path.startsWith("/") ? path : `/${path}`;
      }
      return guildPath(activeGuildId, path);
    },
    [activeGuildId]
  );
}

/**
 * Check if a path is a guild-scoped path.
 * @param path The path to check
 * @returns True if the path starts with /c/:guildId/
 */
export function isGuildScopedPath(path: string): boolean {
  return /^\/c\/\d+\//.test(path);
}

/**
 * Extract the guild ID from a guild-scoped path.
 * @param path The path to extract from
 * @returns The guild ID if present, null otherwise
 */
export function extractGuildIdFromPath(path: string): number | null {
  const match = path.match(/^\/c\/(\d+)/);
  if (!match) return null;
  const id = Number(match[1]);
  return Number.isFinite(id) ? id : null;
}

/**
 * Extract the sub-path from a guild-scoped path (everything after /c/:guildId).
 * @param path The full path
 * @returns The sub-path (e.g., "/projects/47" from "/c/5/projects/47")
 */
export function extractSubPath(path: string): string {
  const match = path.match(/^\/c\/\d+(.*)$/);
  return match ? match[1] || "/" : path;
}

/**
 * Replace the guild ID in a guild-scoped path.
 * @param path The current path
 * @param newGuildId The new guild ID
 * @returns The path with the new guild ID
 */
export function replaceGuildId(path: string, newGuildId: number): string {
  return path.replace(/^\/c\/\d+/, `/c/${newGuildId}`);
}

/**
 * Rewrite a guild-scoped path so it names `initiativeId` as the initiative its
 * entity lives in.
 *
 * Three shapes, because the initiative segment may need replacing, removing, or
 * inserting: a path already under `/i/{other}`, a guild-level path for an
 * entity that does belong to an initiative, and the reverse — an initiative
 * path for an entity that belongs to none (an app's calendar).
 *
 * Returns the path unchanged when it isn't guild-scoped, so a caller can
 * compare the result to decide whether anything needs correcting.
 */
export function canonicalInitiativePath(pathname: string, initiativeId: number | null): string {
  const guild = pathname.match(/^\/c\/(\d+)(\/.*)?$/);
  if (!guild) return pathname;
  const [, guildId, rest = ""] = guild;
  const withoutInitiative = rest.replace(/^\/i\/\d+/, "");
  const prefix = initiativeId === null ? "" : `/i/${initiativeId}`;
  return `/c/${guildId}${prefix}${withoutInitiative}`;
}
