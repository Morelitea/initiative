import { useCallback } from "react";
import { useGuilds } from "@/hooks/useGuilds";

/**
 * Create a guild-scoped URL path.
 * @param guildId The guild ID to scope to
 * @param path The sub-path within the guild (e.g., "/projects" or "projects/47")
 * @returns The full guild-scoped path (e.g., "/g/5/projects/47")
 */
export function guildPath(guildId: number, path: string): string {
  const normalized = path.startsWith("/") ? path : `/${path}`;
  return `/g/${guildId}${normalized}`;
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
 * @returns True if the path starts with /g/:guildId/
 */
export function isGuildScopedPath(path: string): boolean {
  return /^\/g\/\d+\//.test(path);
}

/**
 * Extract the guild ID from a guild-scoped path.
 * @param path The path to extract from
 * @returns The guild ID if present, null otherwise
 */
export function extractGuildIdFromPath(path: string): number | null {
  const match = path.match(/^\/g\/(\d+)/);
  if (!match) return null;
  const id = Number(match[1]);
  return Number.isFinite(id) ? id : null;
}

/**
 * Extract the sub-path from a guild-scoped path (everything after /g/:guildId).
 * @param path The full path
 * @returns The sub-path (e.g., "/projects/47" from "/g/5/projects/47")
 */
export function extractSubPath(path: string): string {
  const match = path.match(/^\/g\/\d+(.*)$/);
  return match ? match[1] || "/" : path;
}

/**
 * Replace the guild ID in a guild-scoped path.
 * @param path The current path
 * @param newGuildId The new guild ID
 * @returns The path with the new guild ID
 */
export function replaceGuildId(path: string, newGuildId: number): string {
  return path.replace(/^\/g\/\d+/, `/g/${newGuildId}`);
}
