import type { RecentItemRead, Tool } from "@/api/generated/initiativeAPI.schemas";
import { guildPath } from "@/lib/guildUrl";
import { RECENTABLE_TOOLS, toolRouteSegment } from "@/lib/tools";

export type RecentKey = {
  entityType: RecentItemRead["entity_type"];
  entityId: number;
  /** Guild parsed from the URL prefix. */
  guildId: number;
};

/**
 * Return the guild-scoped detail-page route for a recent item — the tool's
 * registry route segment plus the entity id.
 *
 * The tabs bar is cross-guild: each tab links into the entity's OWN guild
 * (``item.guild_id``), never the guild the viewer happens to be in —
 * per-guild entity ids collide across guilds, so a tab opened under the
 * wrong guild prefix would resolve to a different (or inaccessible) entity.
 * Navigating the link enters that guild via the /g/$guildId layout.
 */
export function recentRoute(item: RecentItemRead): string {
  const segment = toolRouteSegment(item.entity_type as Tool);
  return guildPath(item.guild_id, `/${segment}/${item.entity_id}`);
}

/** Parse a decimal id from a path segment ("42" → 42, anything else → null). */
function parseId(segment: string | undefined): number | null {
  if (!segment || !/^\d+$/.test(segment)) {
    return null;
  }
  const id = Number.parseInt(segment, 10);
  return Number.isSafeInteger(id) && id >= 0 ? id : null;
}

/**
 * Parse the current location pathname into a ``RecentKey`` so the tabs bar
 * can highlight the active tab. Returns null when no entity detail page is
 * open. Expects ``/g/{guildId}/{toolSegment}/{entityId}/…`` and matches the
 * tool segment against each recentable tool's registry route segment.
 */
export function getActiveRecentKey(pathname: string): RecentKey | null {
  const [, prefix, guildSegment, toolSegment, entitySegment] = pathname.split("/");
  if (prefix !== "g") {
    return null;
  }
  const guildId = parseId(guildSegment);
  const entityId = parseId(entitySegment);
  if (guildId == null || entityId == null) {
    return null;
  }
  for (const tool of RECENTABLE_TOOLS) {
    if (toolRouteSegment(tool) === toolSegment) {
      return { entityType: tool as RecentKey["entityType"], entityId, guildId };
    }
  }
  return null;
}

/**
 * Whether a recent item IS the active detail page. Matches on guild too —
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
