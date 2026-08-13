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
  LayoutDashboard,
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
   * Appears in the recent-items tabs bar. Must mirror the backend's
   * RECENTABLE_TOOLS.
   */
  recents: boolean;
  /** Has a command-palette group. */
  commandPalette: boolean;
  /**
   * Has dedicated notification types. Intentional gap for queues and counter
   * groups — recorded here, not scattered as TODOs.
   */
  notifications: boolean;
  /** Personal cross-guild page under the top-level router, if any. */
  personalRoute: string | null;
  /**
   * Has an export-engine source: single-entity export plus bulk selection
   * export (`{tool}_ids` selectors; a calendar exports as one combined
   * file carrying its events).
   */
  bulkExport: boolean;
  /** Has an import surface: a JSON envelope of this type can be imported
   * (drives the list-page "Import" affordances). Backup import is separate
   * (guild settings), not per-tool. */
  importable: boolean;
}

export const TOOL_REGISTRY: Record<Tool, ToolDef> = {
  [Tool.project]: {
    icon: ListTodo,
    core: true,
    recents: true,
    commandPalette: true,
    notifications: true,
    personalRoute: "/my-projects",
    bulkExport: true,
    importable: true,
  },
  [Tool.document]: {
    icon: ScrollText,
    core: true,
    recents: true,
    commandPalette: true,
    notifications: true,
    personalRoute: "/my-documents",
    bulkExport: true,
    importable: true,
  },
  [Tool.queue]: {
    icon: GalleryHorizontalEnd,
    core: false,
    recents: true,
    commandPalette: true,
    notifications: false,
    personalRoute: null,
    bulkExport: true,
    importable: true,
  },
  [Tool.counter_group]: {
    icon: Gauge,
    core: false,
    recents: true,
    commandPalette: true,
    notifications: false,
    personalRoute: null,
    bulkExport: true,
    importable: true,
  },
  [Tool.calendar]: {
    icon: CalendarDays,
    core: false,
    recents: true,
    commandPalette: true,
    notifications: true,
    personalRoute: "/my-calendar",
    bulkExport: true,
    importable: true,
  },
  [Tool.dashboard]: {
    icon: LayoutDashboard,
    core: false,
    recents: true,
    commandPalette: true,
    notifications: false,
    personalRoute: null,
    bulkExport: false,
    importable: false,
  },
};

/** Every tool, in canonical enum order. */
export const TOOLS = Object.values(Tool) as Tool[];

/** Tools with a per-initiative master switch (everything non-core). */
export const TOGGLEABLE_TOOLS = TOOLS.filter((t) => !TOOL_REGISTRY[t].core);

/** Tools that appear in the recents bar — mirrors backend RECENTABLE_TOOLS. */
export const RECENTABLE_TOOLS = TOOLS.filter((t) => TOOL_REGISTRY[t].recents);

/** Tools with an export-engine source (single + bulk selection export). */
export const BULK_EXPORT_TOOLS = TOOLS.filter((t) => TOOL_REGISTRY[t].bulkExport);
export const IMPORTABLE_TOOLS = TOOLS.filter((t) => TOOL_REGISTRY[t].importable);

/**
 * Sidebar display order within an initiative. Projects render last because the
 * initiative's project list expands directly beneath that row.
 */
export const SIDEBAR_TOOLS: Tool[] = [
  Tool.calendar,
  Tool.dashboard,
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

/** Resource-relative API path (WITHOUT the `/g/{guildId}` segment), e.g. "/api/v1/counter-groups".
 *  Callers must prepend `/api/v1/g/${guildId}` when building guild-scoped requests. */
export const toolApiPath = (tool: Tool): string => `/api/v1/${toolRouteSegment(tool)}`;

/** Guild-relative list route, e.g. "/counter-groups". */
export const toolListRoute = (tool: Tool): string => `/${toolRouteSegment(tool)}`;

/** Export-engine endpoint (relative to /g/{guildId}), e.g. "/exports/counter-group"
 * — the engine's source name is the KEBAB SINGULAR of the tool. */
export const toolExportEndpoint = (tool: Tool): string => `/exports/${tool.replaceAll("_", "-")}`;

/** Single-entity export selector param, e.g. "counter_group_id". */
export const toolExportIdParam = (tool: Tool): string => `${tool}_id`;

/** The envelope ``type`` discriminator a tool's single-entity export emits —
 * the same value its importer registers under: the kebab-singular. */
export const toolEnvelopeType = (tool: Tool): string => `initiative-${tool.replaceAll("_", "-")}`;

/** Inverse of {@link toolEnvelopeType}: which tool an envelope belongs to,
 * or null for an unknown/backup type. */
export const toolForEnvelopeType = (type: string): Tool | null =>
  IMPORTABLE_TOOLS.find((tool) => toolEnvelopeType(tool) === type) ?? null;

/** Bulk-selection export selector param, e.g. "counter_group_ids". */
export const toolExportIdsParam = (tool: Tool): string => `${tool}_ids`;

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

/** Guild-relative sidebar/nav row target for a tool inside an initiative: its
 *  shared list route, filtered to that initiative. Callers prepend the guild
 *  prefix (`useGuildPath`). */
export const toolRowTarget = (
  tool: Tool,
  initiativeId: number
): { to: string; search: { initiativeId: string } } => ({
  to: toolListRoute(tool),
  search: { initiativeId: String(initiativeId) },
});

/** Guild-relative create target for a tool inside an initiative. In-app tools
 *  open their list route's create dialog (`?create=true`); hand-off tools open
 *  their embedded page with a create intent. Callers prepend the guild prefix. */
export const toolCreateTarget = (
  tool: Tool,
  initiativeId: number
): { to: string; search: Record<string, string> } => ({
  to: toolListRoute(tool),
  search: { create: "true", initiativeId: String(initiativeId) },
});
