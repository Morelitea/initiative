/**
 * What a search hit is, and where it goes.
 *
 * A hit names itself (`entity_type`/`entity_id`) and the tool it lives in
 * (`tool`/`tool_id`), which is everything an address needs — so a result links
 * straight to its page rather than through the `/go` resolver.
 *
 * A tool's own row derives from the `Tool` enum. The four entities that live
 * INSIDE a tool are stated once here, in {@link TOOL_CHILDREN}, and that one
 * entry supplies all three things a child needs: which tool it belongs to, the
 * icon it renders with, and how its address is built.
 */

import { CalendarClock, Hash, type LucideIcon, SquareCheckBig, Tag, Ticket } from "lucide-react";

import type { SearchHit } from "@/api/generated/initiativeAPI.schemas";
import { Tool } from "@/api/generated/initiativeAPI.schemas";
import {
  counterRoute,
  eventRoute,
  TOOL_ICONS,
  TOOLS,
  taskRoute,
  toolDetailRoute,
} from "@/lib/tools";

/** The fields routing reads. Hits and palette suggestions both carry them. */
export type SearchTarget = Pick<
  SearchHit,
  "entity_type" | "entity_id" | "initiative_id" | "tool" | "tool_id"
>;

/** The entity type of the guild's vocabulary — the one result that is not in a tool. */
export const TAG_ENTITY_TYPE = "tag";

interface ToolChild {
  /** The tool this lives in — the `tool` a hit carries. */
  tool: Tool;
  icon: LucideIcon;
  /** Address, from the initiative, the parent's id, and the child's own. */
  path: (initiativeId: number | null, parentId: number, entityId: number) => string;
}

/**
 * The entities addressed inside a tool rather than as one.
 *
 * A queue item has no page of its own — a queue is read as a whole — so it
 * lands on its queue.
 */
const TOOL_CHILDREN: Record<string, ToolChild> = {
  task: { tool: Tool.project, icon: SquareCheckBig, path: taskRoute },
  calendar_event: { tool: Tool.calendar, icon: CalendarClock, path: eventRoute },
  counter: { tool: Tool.counter_group, icon: Hash, path: counterRoute },
  queue_item: {
    tool: Tool.queue,
    icon: Ticket,
    path: (initiativeId, queueId) => toolDetailRoute(Tool.queue, initiativeId, queueId),
  },
};

/**
 * Every entity type the Tools tab covers: each tool, plus what lives inside
 * one. The `types` a search asks for and the tabs it is split into come from
 * this, so a new tool joins both by joining the enum.
 */
export const TOOL_ENTITY_TYPES: string[] = [...TOOLS, ...Object.keys(TOOL_CHILDREN)];

/** Which tab a result belongs under. */
export type SearchCategory = "tool" | "tag";

/** The tabs, in the order they are shown. */
export const SEARCH_CATEGORIES: SearchCategory[] = ["tool", "tag"];

/** Where a search lands. Tools is where nearly everything a reader is looking
 *  for lives, so it is the tab to open on rather than one more click away. */
export const DEFAULT_SEARCH_CATEGORY: SearchCategory = "tool";

export const isSearchCategory = (value: unknown): value is SearchCategory =>
  typeof value === "string" && (SEARCH_CATEGORIES as string[]).includes(value);

/** The `types` param restricting a search to one category. */
export const categoryEntityTypes = (category: SearchCategory): string[] =>
  category === "tag" ? [TAG_ENTITY_TYPE] : TOOL_ENTITY_TYPES;

/** The category a hit renders under. */
export const hitCategory = (target: SearchTarget): SearchCategory =>
  target.entity_type === TAG_ENTITY_TYPE ? "tag" : "tool";

/** The icon a hit renders with — its own where it lives inside a tool, its
 *  tool's where it is one. */
export const hitIcon = (target: SearchTarget): LucideIcon => {
  const child = TOOL_CHILDREN[target.entity_type];
  if (child) return child.icon;
  // The guild's vocabulary is the only thing that sits outside a tool.
  return target.tool ? TOOL_ICONS[target.tool] : Tag;
};

/**
 * The guild-relative address of a hit, or `null` when it has none — an entity
 * type this build doesn't route, or a child whose parent didn't come back.
 */
export const searchHitPath = (target: SearchTarget): string | null => {
  if (target.entity_type === TAG_ENTITY_TYPE) return `/tags/${target.entity_id}`;
  const child = TOOL_CHILDREN[target.entity_type];
  if (child) {
    if (target.tool_id == null) return null;
    return child.path(target.initiative_id ?? null, target.tool_id, target.entity_id);
  }
  if (!target.tool) return null;
  return toolDetailRoute(target.tool, target.initiative_id ?? null, target.entity_id);
};
