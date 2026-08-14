/**
 * THE tool registry — the single human-readable place a tool is defined.
 *
 * The canonical tool set is the backend `Tool` enum (mirrored into the
 * generated types). Every derived name follows one rule set, so a tool's
 * entry here is just its icon:
 *
 *   value            "counter_group"          (the enum / resource_type)
 *   plural           "counter_groups"         → permission keys, member flags
 *   kebab plural     "counter-groups"         → route segment, API path
 *   camel plural     "counterGroups"          → i18n namespace, palette group
 *   camel singular   "counterGroup"           → route param name
 *   pascal singular  "CounterGroup"           → nav create-label key
 *
 * ## Adding a tool
 * 1. Backend: add the `Tool` enum member + wire the registries there
 *    (`app/core/tools.py` — its drift tests walk you through the rest).
 * 2. Regenerate types (`pnpm generate:api`).
 * 3. Add ONE entry to `TOOL_ICONS` below.
 * 4. Add the i18n namespace file + nav keys, the route files, and a data
 *    hook — `src/lib/tools.test.ts` fails with a list of exactly what is
 *    missing until every surface exists.
 *
 * There is deliberately NO per-tool capability matrix. Every tool is
 * recentable, taggable, shareable, has a command-palette group, and has a
 * settings page. A tool that genuinely differs is named in ONE exception set
 * below with its reason — the same way `app/core/tools.py` states these facts
 * — so a new tool gets every surface by default and an omission has to be
 * written down to happen.
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
} from "lucide-react";

import type {
  InitiativeMemberRead,
  InitiativeRead,
  PermissionKey,
} from "@/api/generated/initiativeAPI.schemas";
import { Tool } from "@/api/generated/initiativeAPI.schemas";

/**
 * The icon each tool renders with everywhere (sidebar, recents, palette,
 * settings). The one fact about a tool that cannot be derived from its name.
 */
export const TOOL_ICONS: Record<Tool, LucideIcon> = {
  [Tool.project]: ListTodo,
  [Tool.document]: ScrollText,
  [Tool.queue]: GalleryHorizontalEnd,
  [Tool.counter_group]: Gauge,
  [Tool.calendar]: CalendarDays,
  [Tool.dashboard]: LayoutDashboard,
};

/** Every tool, in canonical enum order. */
export const TOOLS = Object.values(Tool) as Tool[];

/**
 * Always on: no per-initiative master switch, visible to every member by
 * default. Mirrors backend `CORE_TOOLS`, and matches the generated
 * `InitiativeRead`, which carries a `{plural}_enabled` column for every OTHER
 * tool and none for these.
 */
export const CORE_TOOLS: ReadonlySet<Tool> = new Set([Tool.project, Tool.document]);

/** Tools with a per-initiative master switch (everything non-core). */
export const TOGGLEABLE_TOOLS = TOOLS.filter((t) => !CORE_TOOLS.has(t));

/**
 * Tools WITHOUT an export-engine source, and why. Stated as an exclusion so
 * the default is "a new tool is portable" — mirrors backend
 * `NON_EXPORTABLE_TOOLS`. Export and import are ONE capability (a tool's JSON
 * envelope round-trips through both), so this set governs each.
 */
export const NON_EXPORTABLE_TOOLS: ReadonlySet<Tool> = new Set([
  // Export/import ships with the marketplace, which owns the definition
  // envelope format.
  Tool.dashboard,
]);

/** Tools with an export-engine source (single + bulk selection export), and
 *  equally the tools whose envelope can be imported. */
export const BULK_EXPORT_TOOLS = TOOLS.filter((t) => !NON_EXPORTABLE_TOOLS.has(t));

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

/** Inverse of {@link toolRouteSegment}: which tool a route segment names, or
 *  null for anything unrecognized. Lets a URL carry a readable tool selector. */
export const toolForRouteSegment = (segment: string): Tool | null =>
  TOOLS.find((tool) => toolRouteSegment(tool) === segment) ?? null;

/** "counter_group" → "counterGroups" — i18n namespace, palette group key. */
export const toolCamelPlural = (tool: Tool): string =>
  toolPlural(tool).replace(/_(\w)/g, (_, c: string) => c.toUpperCase());

/** "counter_group" → "counterGroup" — the stem of the route param name. */
export const toolCamelSingular = (tool: Tool): string =>
  tool.replace(/_(\w)/g, (_, c: string) => c.toUpperCase());

/** "counter_group" → "CounterGroup" */
export const toolPascalSingular = (tool: Tool): string =>
  tool.replace(/(?:^|_)(\w)/g, (_, c: string) => c.toUpperCase());

/** Resource-relative API path (WITHOUT the `/g/{guildId}` segment), e.g. "/api/v1/counter-groups".
 *  Callers must prepend `/api/v1/g/${guildId}` when building guild-scoped requests. */
export const toolApiPath = (tool: Tool): string => `/api/v1/${toolRouteSegment(tool)}`;

/** Guild-relative list route, e.g. "/counter-groups". */
export const toolListRoute = (tool: Tool): string => `/${toolRouteSegment(tool)}`;

/** Guild-relative detail route for one entity, e.g. "/counter-groups/12". */
export const toolDetailRoute = (tool: Tool, id: number): string => `${toolListRoute(tool)}/${id}`;

/** Guild-relative settings route for one entity, e.g. "/counter-groups/12/settings". */
export const toolSettingsRoute = (tool: Tool, id: number): string =>
  `${toolDetailRoute(tool, id)}/settings`;

/** The router path param carrying a tool entity's id, e.g. "counterGroupId".
 *  Every tool's detail/settings route names its param this way, so the shared
 *  settings page reads the id without a per-tool lookup. */
export const toolParamName = (tool: Tool): string => `${toolCamelSingular(tool)}Id`;

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
  BULK_EXPORT_TOOLS.find((tool) => toolEnvelopeType(tool) === type) ?? null;

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
  CORE_TOOLS.has(tool) ||
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
