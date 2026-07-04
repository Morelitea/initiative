import type { LucideIcon } from "lucide-react";
import {
  CalendarDays,
  GalleryHorizontalEnd,
  Gauge,
  ListTodo,
  ScrollText,
  Sparkles,
} from "lucide-react";

import type {
  InitiativeMemberRead,
  InitiativeRead,
  PermissionKey,
} from "@/api/generated/initiativeAPI.schemas";
import { Tool } from "@/api/generated/initiativeAPI.schemas";

/**
 * The single source of truth for the app's per-initiative "tools".
 *
 * Every surface that used to hand-write one copy per tool — the sidebar, the
 * initiative tabs, the settings feature toggles, the role-permission cards, the
 * command palette, the create menus, the recent-item icons — now derives from
 * this one array. Adding a tool (or wiring an existing one into a new surface)
 * is a single edit here instead of a scavenger hunt across ~8 files, and the
 * asymmetries that used to creep in (a tool missing from one menu, a permission
 * key that drifted) become structurally impossible.
 *
 * `id` is the backend `Tool` enum value — the same string used as
 * `resource_grants.resource_type`, the recents/trash `entity_type`, and the URL
 * segment stem — so it threads cleanly through the API layer.
 */

/** The per-initiative feature flags on {@link InitiativeRead} (the toggles). */
export type InitiativeEnableFlag =
  | "queues_enabled"
  | "events_enabled"
  | "counters_enabled"
  | "advanced_tool_enabled";

/** Which settings section / permission accordion a tool's card lives under. */
export type ToolSection = "core" | "advanced" | "advancedTool";

export interface ToolPerm {
  /** Role permission key gating visibility. */
  view: PermissionKey;
  /** Role permission key gating creation. */
  create: PermissionKey;
  /** Per-user resolved membership boolean for visibility. */
  membershipView: keyof InitiativeMemberRead;
  /** Per-user resolved membership boolean for creation. */
  membershipCreate: keyof InitiativeMemberRead;
  /** i18n key (initiatives ns) for the "view" permission label. */
  viewLabelKey: string;
  /** i18n key (initiatives ns) for the "create" permission label. */
  createLabelKey: string;
  /** i18n key (initiatives ns) for the permission card title. */
  groupLabelKey: string;
}

export interface ToolNav {
  /** i18n key (nav ns) for the sidebar/nav label. */
  labelKey: string;
  /** i18n key (nav ns) for the "create X" affordance. */
  createLabelKey: string;
  /** Guild-relative list route, e.g. "/queues". */
  listRoute: string;
  /** Whether the sidebar row shows an item count. */
  hasCount: boolean;
  /**
   * Whether this tool can be created "from anywhere" by navigating to its list
   * route with `?create=true` — i.e. its create dialog has an initiative picker
   * and needs no pre-selected initiative. Drives the global create surfaces
   * (command palette). Events are excluded (their dialog requires an initiative).
   */
  navCreateGlobal?: boolean;
}

export interface ToolSettingsToggle {
  /** i18n key (initiatives ns) for the toggle title. */
  titleKey: string;
  /** i18n key (initiatives ns) for the toggle description. */
  descriptionKey: string;
}

export interface ToolDef {
  /** Backend `Tool` enum value — resource_type / entity_type / route stem. */
  id: Tool;
  /** Icon used everywhere the tool appears (nav, command palette, recents). */
  icon: LucideIcon;
  /** Settings section / permission accordion the tool belongs to. */
  section: ToolSection;
  /**
   * Initiative-level enable flag, or `null` for always-on tools (documents,
   * projects) which have no per-initiative toggle.
   */
  enableFlag: InitiativeEnableFlag | null;
  /**
   * Only visible when the deployment configures an advanced tool at runtime
   * (`useAppConfig().advancedTool`). advanced_tool only.
   */
  runtimeConfigGated: boolean;
  /** Shareable through the standard `resource_grants` DAC (bulk "Edit access"). */
  shareable: boolean;
  /** Role/membership permission wiring. */
  perm: ToolPerm;
  /**
   * Sidebar / nav rendering data. Absent for tools with no standard list route
   * (advanced_tool, which renders a bespoke pinned entry per initiative).
   */
  nav?: ToolNav;
  /** Feature toggle shown in initiative settings — only tools with an enableFlag. */
  settingsToggle?: ToolSettingsToggle;
}

export const TOOLS: ToolDef[] = [
  {
    id: Tool.document,
    icon: ScrollText,
    section: "core",
    enableFlag: null,
    runtimeConfigGated: false,
    shareable: true,
    perm: {
      view: "docs_enabled",
      create: "create_docs",
      membershipView: "can_view_docs",
      membershipCreate: "can_create_docs",
      viewLabelKey: "settings.permissions.viewDocuments",
      createLabelKey: "settings.permissions.createDocuments",
      groupLabelKey: "settings.permissionGroups.documents",
    },
    nav: {
      labelKey: "documents",
      createLabelKey: "createDocument",
      listRoute: "/documents",
      hasCount: true,
    },
  },
  {
    id: Tool.project,
    icon: ListTodo,
    section: "core",
    enableFlag: null,
    runtimeConfigGated: false,
    shareable: true,
    perm: {
      view: "projects_enabled",
      create: "create_projects",
      membershipView: "can_view_projects",
      membershipCreate: "can_create_projects",
      viewLabelKey: "settings.permissions.viewProjects",
      createLabelKey: "settings.permissions.createProjects",
      groupLabelKey: "settings.permissionGroups.projects",
    },
    nav: {
      labelKey: "projects",
      createLabelKey: "createProject",
      listRoute: "/projects",
      hasCount: true,
      navCreateGlobal: true,
    },
  },
  {
    id: Tool.queue,
    icon: GalleryHorizontalEnd,
    section: "advanced",
    enableFlag: "queues_enabled",
    runtimeConfigGated: false,
    shareable: true,
    perm: {
      view: "queues_enabled",
      create: "create_queues",
      membershipView: "can_view_queues",
      membershipCreate: "can_create_queues",
      viewLabelKey: "settings.permissions.viewQueues",
      createLabelKey: "settings.permissions.createQueues",
      groupLabelKey: "settings.permissionGroups.queues",
    },
    nav: {
      labelKey: "queues",
      createLabelKey: "createQueue",
      listRoute: "/queues",
      hasCount: true,
      navCreateGlobal: true,
    },
    settingsToggle: {
      titleKey: "queuesFeature",
      descriptionKey: "queuesFeatureDescription",
    },
  },
  {
    id: Tool.calendar_event,
    icon: CalendarDays,
    section: "advanced",
    enableFlag: "events_enabled",
    runtimeConfigGated: false,
    shareable: true,
    perm: {
      view: "events_enabled",
      create: "create_events",
      membershipView: "can_view_events",
      membershipCreate: "can_create_events",
      viewLabelKey: "settings.permissions.viewEvents",
      createLabelKey: "settings.permissions.createEvents",
      groupLabelKey: "settings.permissionGroups.events",
    },
    nav: {
      labelKey: "events",
      createLabelKey: "createEvent",
      listRoute: "/events",
      hasCount: false,
    },
    settingsToggle: {
      titleKey: "eventsFeature",
      descriptionKey: "eventsFeatureDescription",
    },
  },
  {
    id: Tool.counter_group,
    icon: Gauge,
    section: "advanced",
    enableFlag: "counters_enabled",
    runtimeConfigGated: false,
    shareable: true,
    perm: {
      view: "counters_enabled",
      create: "create_counters",
      membershipView: "can_view_counters",
      membershipCreate: "can_create_counters",
      viewLabelKey: "settings.permissions.viewCounters",
      createLabelKey: "settings.permissions.createCounters",
      groupLabelKey: "settings.permissionGroups.counters",
    },
    nav: {
      labelKey: "counters",
      createLabelKey: "createCounterGroup",
      listRoute: "/counter-groups",
      hasCount: true,
      navCreateGlobal: true,
    },
    settingsToggle: {
      titleKey: "countersFeature",
      descriptionKey: "countersFeatureDescription",
    },
  },
  {
    id: Tool.advanced_tool,
    icon: Sparkles,
    section: "advancedTool",
    enableFlag: "advanced_tool_enabled",
    runtimeConfigGated: true,
    shareable: true,
    perm: {
      view: "advanced_tool_enabled",
      create: "create_advanced_tool",
      membershipView: "can_view_advanced_tool",
      membershipCreate: "can_create_advanced_tool",
      viewLabelKey: "settings.permissions.viewAdvancedTool",
      createLabelKey: "settings.permissions.createAdvancedTool",
      groupLabelKey: "settings.permissionGroups.advancedTool",
    },
    // No `nav`: the advanced tool renders a bespoke pinned entry (its label is
    // the runtime deployment name, and it links to a per-initiative route).
    settingsToggle: {
      // `titleKey` is overridden by the runtime advanced-tool name at render.
      titleKey: "advancedTools",
      descriptionKey: "advancedToolFeatureDescription",
    },
  },
];

/** Lookup by `Tool` id. */
export const TOOL_BY_ID: Record<Tool, ToolDef> = Object.fromEntries(
  TOOLS.map((tool) => [tool.id, tool])
) as Record<Tool, ToolDef>;

/** Tools in a given settings section, in registry order. */
export const toolsInSection = (section: ToolSection): ToolDef[] =>
  TOOLS.filter((tool) => tool.section === section);

/** Tools that carry an initiative-level feature toggle, in registry order. */
export const TOGGLEABLE_TOOLS: ToolDef[] = TOOLS.filter((tool) => tool.enableFlag !== null);

/**
 * Icon for an entity/resource type string (recents, command palette, dashboards).
 * Returns `undefined` for types with no fixed tool icon (e.g. documents, whose
 * icon depends on file type, or non-tool entities like tasks/comments) so the
 * caller can fall back.
 */
export const toolIcon = (entityType: string): LucideIcon | undefined =>
  TOOL_BY_ID[entityType as Tool]?.icon;

/** A tool's effective visibility/creation for one user in one initiative. */
export interface ToolAccess {
  view: boolean;
  create: boolean;
}

export type ToolAccessMap = Record<Tool, ToolAccess>;

const isEnabled = (initiative: InitiativeRead, tool: ToolDef): boolean =>
  tool.enableFlag === null ? true : (initiative[tool.enableFlag] ?? false);

/**
 * Full access to every enabled tool (guild admin or read/write grant). `canCreate`
 * toggles the create affordances (a read-only grant sees but can't author).
 */
export const fullToolAccess = (initiative: InitiativeRead, canCreate: boolean): ToolAccessMap =>
  Object.fromEntries(
    TOOLS.map((tool) => {
      const enabled = isEnabled(initiative, tool);
      return [tool.id, { view: enabled, create: canCreate && enabled }];
    })
  ) as ToolAccessMap;

/** Bare read of always-on tools (documents/projects) for a non-member with no grant. */
export const readOnlyToolAccess = (): ToolAccessMap =>
  Object.fromEntries(
    TOOLS.map((tool) => [tool.id, { view: tool.enableFlag === null, create: false }])
  ) as ToolAccessMap;

/** Per-tool access resolved from a user's initiative membership row. */
export const membershipToolAccess = (membership: InitiativeMemberRead): ToolAccessMap =>
  Object.fromEntries(
    TOOLS.map((tool) => {
      // Always-on tools (docs/projects) historically default to visible.
      const viewDefault = tool.enableFlag === null;
      return [
        tool.id,
        {
          view: (membership[tool.perm.membershipView] as boolean | undefined) ?? viewDefault,
          create: (membership[tool.perm.membershipCreate] as boolean | undefined) ?? false,
        },
      ];
    })
  ) as ToolAccessMap;
