import type { RecentItemRead } from "@/api/generated/initiativeAPI.schemas";
import { guildPath } from "@/lib/guildUrl";

export type RecentKey = {
  entityType: RecentItemRead["entity_type"];
  entityId: number;
};

const SEGMENT_BY_TYPE: Record<RecentItemRead["entity_type"], string> = {
  project: "projects",
  document: "documents",
  queue: "queues",
  counter_group: "counter-groups",
};

/**
 * Return the guild-scoped detail-page route for a recent item.
 *
 * If ``activeGuildId`` is null we fall back to the legacy un-prefixed path so
 * the bar still works for users who reach a detail page outside a guild
 * context (e.g. cross-guild user pages).
 */
export function recentRoute(item: RecentItemRead, activeGuildId: number | null): string {
  const segment = SEGMENT_BY_TYPE[item.entity_type];
  const path = `/${segment}/${item.entity_id}`;
  return activeGuildId ? guildPath(activeGuildId, path) : path;
}

/**
 * Parse the current location pathname into a ``RecentKey`` so the tabs bar
 * can highlight the active tab. Returns null when no entity detail page is
 * open.
 */
export function getActiveRecentKey(pathname: string): RecentKey | null {
  // Match both old (``/projects/:id``) and new (``/g/:guildId/projects/:id``).
  const patterns: Array<{
    entityType: RecentItemRead["entity_type"];
    re: RegExp;
  }> = [
    { entityType: "project", re: /^\/g\/\d+\/projects\/(\d+)/ },
    { entityType: "project", re: /^\/projects\/(\d+)/ },
    { entityType: "document", re: /^\/g\/\d+\/documents\/(\d+)/ },
    { entityType: "document", re: /^\/documents\/(\d+)/ },
    { entityType: "queue", re: /^\/g\/\d+\/queues\/(\d+)/ },
    { entityType: "queue", re: /^\/queues\/(\d+)/ },
    { entityType: "counter_group", re: /^\/g\/\d+\/counter-groups\/(\d+)/ },
    { entityType: "counter_group", re: /^\/counter-groups\/(\d+)/ },
  ];

  for (const { entityType, re } of patterns) {
    const m = pathname.match(re);
    if (m) {
      return { entityType, entityId: Number(m[1]) };
    }
  }
  return null;
}
