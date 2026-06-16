import type { RecentItemRead } from "@/api/generated/initiativeAPI.schemas";
import { guildPath } from "@/lib/guildUrl";

export type RecentKey = {
  entityType: RecentItemRead["entity_type"];
  entityId: number;
  /** Guild parsed from the URL prefix. */
  guildId: number;
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
 * The tabs bar is cross-guild: each tab links into the entity's OWN guild
 * (``item.guild_id``), never the guild the viewer happens to be in —
 * per-guild entity ids collide across guilds, so a tab opened under the
 * wrong guild prefix would resolve to a different (or inaccessible) entity.
 * Navigating the link enters that guild via the /g/$guildId layout.
 */
export function recentRoute(item: RecentItemRead): string {
  const segment = SEGMENT_BY_TYPE[item.entity_type];
  return guildPath(item.guild_id, `/${segment}/${item.entity_id}`);
}

/**
 * Parse the current location pathname into a ``RecentKey`` so the tabs bar
 * can highlight the active tab. Returns null when no entity detail page is
 * open.
 */
export function getActiveRecentKey(pathname: string): RecentKey | null {
  const patterns: Array<{
    entityType: RecentItemRead["entity_type"];
    re: RegExp;
  }> = [
    { entityType: "project", re: /^\/g\/(\d+)\/projects\/(\d+)/ },
    { entityType: "document", re: /^\/g\/(\d+)\/documents\/(\d+)/ },
    { entityType: "queue", re: /^\/g\/(\d+)\/queues\/(\d+)/ },
    { entityType: "counter_group", re: /^\/g\/(\d+)\/counter-groups\/(\d+)/ },
  ];

  for (const { entityType, re } of patterns) {
    const m = pathname.match(re);
    if (m) {
      return { entityType, entityId: Number(m[2]), guildId: Number(m[1]) };
    }
  }
  return null;
}

/**
 * True when ``activeKey`` (parsed from the URL) refers to ``item``.
 *
 * Entity ids are only unique within a guild, so the guild must match too —
 * otherwise a guild-A document tab would light up while viewing guild B's
 * document that happens to share the id.
 */
export function recentKeyMatches(activeKey: RecentKey | null, item: RecentItemRead): boolean {
  if (!activeKey) {
    return false;
  }
  return (
    activeKey.entityType === item.entity_type &&
    activeKey.entityId === item.entity_id &&
    activeKey.guildId === item.guild_id
  );
}
