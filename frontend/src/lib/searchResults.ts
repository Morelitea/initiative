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

import {
  CalendarClock,
  Hash,
  type LucideIcon,
  MessageSquare,
  SquareCheckBig,
  Tag,
  Ticket,
} from "lucide-react";

import type { SearchHit } from "@/api/generated/initiativeAPI.schemas";
import { SearchEntityType, Tool } from "@/api/generated/initiativeAPI.schemas";
import { counterRoute, eventRoute, TOOL_ICONS, taskRoute, toolDetailRoute } from "@/lib/tools";

/** The fields routing reads. Hits and palette suggestions both carry them. */
export type SearchTarget = Pick<
  SearchHit,
  "entity_type" | "entity_id" | "initiative_id" | "tool" | "tool_id"
>;

/** The guild's vocabulary — the one result that lives in no tool. */
export const TAG_ENTITY_TYPE = SearchEntityType.tag;
/** What people said on the content. */
export const COMMENT_ENTITY_TYPE = SearchEntityType.comment;

interface ToolChild {
  /** The tool this lives in — the `tool` a hit carries. */
  tool: Tool;
  icon: LucideIcon;
  /** Address, from the initiative, the parent's id, the child's own, and the
   *  tool the hit named — which is fixed for most, and per-row for a comment. */
  path: (initiativeId: number | null, parentId: number, entityId: number, tool: Tool) => string;
}

/**
 * The entities addressed inside a tool rather than as one.
 *
 * A queue item has no page of its own — a queue is read as a whole — so it
 * lands on its queue.
 */
const TOOL_CHILDREN: Partial<Record<SearchEntityType, ToolChild>> = {
  [SearchEntityType.task]: { tool: Tool.project, icon: SquareCheckBig, path: taskRoute },
  [SearchEntityType.calendar_event]: {
    tool: Tool.calendar,
    icon: CalendarClock,
    path: eventRoute,
  },
  [SearchEntityType.counter]: { tool: Tool.counter_group, icon: Hash, path: counterRoute },
  [SearchEntityType.queue_item]: {
    tool: Tool.queue,
    icon: Ticket,
    path: (initiativeId, queueId) => toolDetailRoute(Tool.queue, initiativeId, queueId),
  },
  // A comment is read on the thing it is on, so it goes there. Its own id
  // addresses nothing: there is no page for one comment.
  [SearchEntityType.comment]: {
    tool: Tool.project,
    icon: MessageSquare,
    path: (initiativeId, parentId, _entityId, tool) =>
      toolDetailRoute(tool, initiativeId, parentId),
  },
};

/**
 * Every entity type the Tools tab covers: each tool, plus what lives inside one
 * — which is every indexed type that is neither a tag nor a comment. Derived
 * from the generated enum, so a tool added server-side is searched here without
 * an edit; a type this build does not know still renders, unaddressed.
 */
export const TOOL_ENTITY_TYPES: SearchEntityType[] = Object.values(SearchEntityType).filter(
  (type) => type !== TAG_ENTITY_TYPE && type !== COMMENT_ENTITY_TYPE
);

/** Which tab a result belongs under. */
export type SearchCategory = "tool" | "member" | "comment" | "tag";

/** The tabs, in the order they are shown. Members sit second: who is here is
 *  asked about nearly as often as what is here, and far more often than what
 *  was said about it. */
export const SEARCH_CATEGORIES: SearchCategory[] = ["tool", "member", "comment", "tag"];

/** Where a search lands. Tools is where nearly everything a reader is looking
 *  for lives, so it is the tab to open on rather than one more click away. */
export const DEFAULT_SEARCH_CATEGORY: SearchCategory = "tool";

export const isSearchCategory = (value: unknown): value is SearchCategory =>
  typeof value === "string" && (SEARCH_CATEGORIES as string[]).includes(value);

/**
 * The `types` param restricting a search to one category, or `null` where the
 * category is not in the index at all.
 *
 * Members are people, not content: they live in the shared tables that identity
 * lives in, not in a community's own schema, so they are asked for from the
 * roster rather than found in the index. `null` is what says so.
 */
export const categoryEntityTypes = (category: SearchCategory): SearchEntityType[] | null => {
  if (category === "member") return null;
  if (category === "tag") return [TAG_ENTITY_TYPE];
  if (category === "comment") return [COMMENT_ENTITY_TYPE];
  return TOOL_ENTITY_TYPES;
};

/** The category a hit renders under. */
export const hitCategory = (target: SearchTarget): SearchCategory => {
  if (target.entity_type === TAG_ENTITY_TYPE) return "tag";
  if (target.entity_type === COMMENT_ENTITY_TYPE) return "comment";
  return "tool";
};

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
    if (target.tool_id == null || !target.tool) return null;
    return child.path(target.initiative_id ?? null, target.tool_id, target.entity_id, target.tool);
  }
  if (!target.tool) return null;
  return toolDetailRoute(target.tool, target.initiative_id ?? null, target.entity_id);
};
