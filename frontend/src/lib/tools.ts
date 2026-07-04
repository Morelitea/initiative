/**
 * THE tool registry — the single human-readable place a tool is defined.
 *
 * The canonical tool set is the backend `Tool` enum (mirrored into the
 * generated types). Every derived name follows one rule set, so a tool's
 * entry here is just its icon plus honest capability flags:
 *
 *   value            "counter_group"          (the enum / resource_type)
 *   plural           "counter_groups"         → permission keys, member flags
 *   kebab plural     "counter-groups"         → route segment, API path
 *   camel plural     "counterGroups"          → i18n namespace, palette group
 *   pascal singular  "CounterGroup"           → nav create-label key
 *
 * ## Adding a tool
 * 1. Backend: add the `Tool` enum member + wire the registries there
 *    (`app/core/tools.py` — its drift tests walk you through the rest).
 * 2. Regenerate types (`pnpm generate:api`).
 * 3. Add ONE entry to `TOOL_REGISTRY` below.
 * 4. Add the i18n namespace file + nav keys, the route files, and a data
 *    hook — `src/lib/tools.test.ts` fails with a list of exactly what is
 *    missing until every surface exists.
 *
 * Capability flags are deliberate product decisions, not omissions — a flag
 * set to `false` documents an intentional gap (e.g. no notification types
 * for queues yet), and the drift tests hold the rest of the app to whatever
 * is declared here.
 */

import type { ParseKeys } from "i18next";
import {
  CalendarDays,
  GalleryHorizontalEnd,
  Gauge,
  ListTodo,
  type LucideIcon,
  ScrollText,
  Sparkles,
} from "lucide-react";

import type {
  InitiativeMemberRead,
  InitiativeRead,
  PermissionKey,
} from "@/api/generated/initiativeAPI.schemas";
import { Tool } from "@/api/generated/initiativeAPI.schemas";

export interface ToolDef {
  /** Icon used everywhere the tool renders (sidebar, recents, palette). */
  icon: LucideIcon;
  /**
   * Core tools are always on: no per-initiative master switch, visible to
   * every member by default. Non-core tools are opt-in per initiative via
   * their `{plural}_enabled` switch.
   */
  core: boolean;
  /**
   * Sidebar count badge + count query. Calendar events deliberately have
   * none (a total event count is time-window-dependent and meaningless);
   * the advanced tool renders as a single link, not a counted collection.
   */
  sidebarCount: boolean;
  /**
   * Appears in the recent-items tabs bar. Must mirror the backend's
   * RECENTABLE_TOOLS (the advanced tool has no detail route to return to).
   */
  recents: boolean;
  /** Has a command-palette group (or, for the advanced tool, nav entries). */
  commandPalette: boolean;
  /**
   * Has dedicated notification types. Intentional gap for queues, counter
   * groups, and advanced tools — recorded here, not scattered as TODOs.
   */
  notifications: boolean;
  /** Personal cross-guild page under the top-level router, if any. */
  personalRoute: string | null;
  /**
   * The tool's rows are created inside the app. The advanced tool's content
   * is authored in the external service (name comes from runtime
   * config), so its create affordance is a hand-off, not a dialog.
   */
  inAppCreate: boolean;
}

export const TOOL_REGISTRY: Record<Tool, ToolDef> = {
  [Tool.project]: {
    icon: ListTodo,
    core: true,
    sidebarCount: true,
    recents: true,
    commandPalette: true,
    notifications: true,
    personalRoute: "/my-projects",
    inAppCreate: true,
  },
  [Tool.document]: {
    icon: ScrollText,
    core: true,
    sidebarCount: true,
    recents: true,
    commandPalette: true,
    notifications: true,
    personalRoute: "/my-documents",
    inAppCreate: true,
  },
  [Tool.queue]: {
    icon: GalleryHorizontalEnd,
    core: false,
    sidebarCount: true,
    recents: true,
    commandPalette: true,
    notifications: false,
    personalRoute: null,
    inAppCreate: true,
  },
  [Tool.counter_group]: {
    icon: Gauge,
    core: false,
    sidebarCount: true,
    recents: true,
    commandPalette: true,
    notifications: false,
    personalRoute: null,
    inAppCreate: true,
  },
  [Tool.calendar_event]: {
    icon: CalendarDays,
    core: false,
    sidebarCount: false,
    recents: true,
    commandPalette: true,
    notifications: true,
    personalRoute: "/my-calendar-events",
    inAppCreate: true,
  },
  [Tool.advanced_tool]: {
    icon: Sparkles,
    core: false,
    sidebarCount: false,
    recents: false,
    commandPalette: true,
    notifications: false,
    personalRoute: null,
    inAppCreate: false,
  },
};

/** Every tool, in canonical enum order. */
export const TOOLS = Object.values(Tool) as Tool[];

/** Tools with a per-initiative master switch (everything non-core). */
export const TOGGLEABLE_TOOLS = TOOLS.filter((t) => !TOOL_REGISTRY[t].core);

/** Tools that appear in the recents bar — mirrors backend RECENTABLE_TOOLS. */
export const RECENTABLE_TOOLS = TOOLS.filter((t) => TOOL_REGISTRY[t].recents);

/**
 * Sidebar display order within an initiative. The advanced tool is pinned to
 * the top when its integration is on; projects render last because the
 * initiative's project list expands directly beneath that row.
 */
export const SIDEBAR_TOOLS: Tool[] = [
  Tool.advanced_tool,
  Tool.calendar_event,
  Tool.document,
  Tool.queue,
  Tool.counter_group,
  Tool.project,
];

// ---------------------------------------------------------------------------
// Derived names — one rule each, no per-tool tables.
// ---------------------------------------------------------------------------

/** "counter_group" → "counter_groups" */
export const toolPlural = (tool: Tool): string => `${tool}s`;

/** "counter_group" → "counter-groups" — route segment AND API path segment. */
export const toolRouteSegment = (tool: Tool): string => toolPlural(tool).replaceAll("_", "-");

/** "counter_group" → "counterGroups" — i18n namespace, palette group key. */
export const toolCamelPlural = (tool: Tool): string =>
  toolPlural(tool).replace(/_(\w)/g, (_, c: string) => c.toUpperCase());

/** "counter_group" → "CounterGroup" */
export const toolPascalSingular = (tool: Tool): string =>
  tool.replace(/(?:^|_)(\w)/g, (_, c: string) => c.toUpperCase());

/** Guild-scoped API path prefix, e.g. "/api/v1/counter-groups". */
export const toolApiPath = (tool: Tool): string => `/api/v1/${toolRouteSegment(tool)}`;

/** Guild-relative list route, e.g. "/counter-groups". */
export const toolListRoute = (tool: Tool): string => `/${toolRouteSegment(tool)}`;

/** nav.json label key, e.g. "counterGroups". Typed against the nav namespace
 * so `t(toolNavLabelKey(tool))` satisfies typed i18next — the drift test
 * asserts the key actually exists for every tool. */
export const toolNavLabelKey = (tool: Tool): ParseKeys<"nav"> =>
  toolCamelPlural(tool) as ParseKeys<"nav">;

/** nav.json create-label key, e.g. "createCounterGroup". */
export const toolCreateLabelKey = (tool: Tool): ParseKeys<"nav"> =>
  `create${toolPascalSingular(tool)}` as ParseKeys<"nav">;

/** Role permission key gating viewing, e.g. "counter_groups_enabled". */
export const toolViewPermission = (tool: Tool): PermissionKey =>
  `${toolPlural(tool)}_enabled` as PermissionKey;

/** Role permission key gating creation, e.g. "create_counter_groups". */
export const toolCreatePermission = (tool: Tool): PermissionKey =>
  `create_${toolPlural(tool)}` as PermissionKey;

/** Membership view flag, e.g. "can_view_counter_groups". */
export const toolMemberViewFlag = (tool: Tool): keyof InitiativeMemberRead =>
  `can_view_${toolPlural(tool)}` as keyof InitiativeMemberRead;

/** Membership create flag, e.g. "can_create_counter_groups". */
export const toolMemberCreateFlag = (tool: Tool): keyof InitiativeMemberRead =>
  `can_create_${toolPlural(tool)}` as keyof InitiativeMemberRead;

/**
 * The initiative master-switch field for a toggleable tool (same spelling as
 * the view permission). Core tools have no switch — callers get `true`.
 */
export const isToolEnabled = (tool: Tool, initiative: InitiativeRead): boolean =>
  TOOL_REGISTRY[tool].core ||
  Boolean(initiative[`${toolPlural(tool)}_enabled` as keyof InitiativeRead]);
