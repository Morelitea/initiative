/**
 * Tool-registry drift tests — every per-tool surface must cover exactly what
 * the registry declares. A new tool (or a renamed key) fails here with a
 * message naming the missing surface, instead of silently shipping a tool
 * that's absent from the sidebar, palette, trash, recents, or i18n.
 *
 * Mirrors the backend's app/core/tools_test.py, which pins the same
 * derivations on the API side.
 */
import { describe, expect, it } from "vitest";

import {
  EntityType,
  PermissionKey,
  RecentEntityType,
  Tool,
} from "@/api/generated/initiativeAPI.schemas";
import { PALETTE_TOOLS, TOOL_PALETTE } from "@/lib/toolPalette";
import {
  counterRoute,
  entityRefRoute,
  eventRoute,
  INITIATIVES_ROUTE,
  initiativeRoute,
  NON_EXPORTABLE_TOOLS,
  SIDEBAR_TOOLS,
  TOGGLEABLE_TOOLS,
  TOOL_ICONS,
  TOOLS,
  taskRoute,
  toolCamelPlural,
  toolCamelSingular,
  toolCreateLabelKey,
  toolCreatePermission,
  toolDetailRoute,
  toolListRoute,
  toolNavLabelKey,
  toolParamName,
  toolPascalSingular,
  toolRefRoute,
  toolRouteSegment,
  toolSettingsRoute,
  toolViewPermission,
} from "@/lib/tools";

import access from "../../public/locales/en/access.json";
import command from "../../public/locales/en/command.json";
import guildHome from "../../public/locales/en/guildHome.json";
import initiatives from "../../public/locales/en/initiatives.json";
import nav from "../../public/locales/en/nav.json";
import trash from "../../public/locales/en/trash.json";

// Route files (keys only — nothing is loaded). The guild tree holds each
// tool's tab, detail, and settings routes, nested under their initiative.
const guildRouteFiles = Object.keys(
  import.meta.glob("../routes/_serverRequired/_authenticated/g/$guildId/**/*.tsx")
);
const INITIATIVE_ROUTES = "../routes/_serverRequired/_authenticated/g/$guildId/i/$initiativeId";
// Locale namespace files across every shipped language.
const localeFiles = Object.keys(import.meta.glob("../../public/locales/*/*.json"));
const locales = [...new Set(localeFiles.map((f) => f.split("/").at(-2)))];

describe("tool registry", () => {
  it("covers exactly the canonical Tool enum", () => {
    expect(Object.keys(TOOL_ICONS).sort()).toEqual(Object.values(Tool).sort());
  });

  it("sidebar order is a permutation of the tools", () => {
    expect([...SIDEBAR_TOOLS].sort()).toEqual([...TOOLS].sort());
  });

  it("derives the exact permission keys the API exposes", () => {
    const derived = TOOLS.flatMap((tool) => [toolViewPermission(tool), toolCreatePermission(tool)]);
    expect(derived.sort()).toEqual(Object.values(PermissionKey).sort());
  });

  it("every tool is recentable, matching the backend's RecentEntityType", () => {
    expect(TOOLS.map(String).sort()).toEqual(Object.values(RecentEntityType).sort());
  });

  it("every tool is a trash entity type with a label", () => {
    const trashTypes = Object.values(EntityType) as string[];
    const labels = trash.entityType as Record<string, string>;
    for (const tool of TOOLS) {
      expect(trashTypes, `missing EntityType for ${tool}`).toContain(tool);
    }
    for (const entityType of trashTypes) {
      expect(labels[entityType], `missing trash.json entityType.${entityType}`).toBeTruthy();
    }
  });
});

describe("tool i18n", () => {
  it("nav has a label and create label for every tool", () => {
    const keys = nav as Record<string, string>;
    for (const tool of TOOLS) {
      expect(keys[toolNavLabelKey(tool)], `missing nav.json ${toolNavLabelKey(tool)}`).toBeTruthy();
      expect(
        keys[toolCreateLabelKey(tool)],
        `missing nav.json ${toolCreateLabelKey(tool)}`
      ).toBeTruthy();
    }
  });

  it("every tool has its namespace file in every locale", () => {
    for (const locale of locales) {
      for (const tool of TOOLS) {
        const file = `../../public/locales/${locale}/${toolCamelPlural(tool)}.json`;
        expect(localeFiles, `missing ${file}`).toContain(file);
      }
    }
  });

  it("guild home names every tool's own table column", () => {
    const detail = guildHome.columns.detail as Record<string, string>;
    for (const tool of TOOLS) {
      expect(
        detail[toolCamelPlural(tool)],
        `missing guildHome.json columns.detail.${toolCamelPlural(tool)}`
      ).toBeTruthy();
    }
  });

  it("command palette has a group label for every palette-enabled tool", () => {
    const groups = command.groups as Record<string, string>;
    for (const tool of PALETTE_TOOLS) {
      expect(
        groups[toolCamelPlural(tool)],
        `missing command.json groups.${toolCamelPlural(tool)}`
      ).toBeTruthy();
    }
  });

  it("bulk access bar has labels for every tool", () => {
    const bulkBar = access.bulkBar as Record<string, string>;
    for (const tool of TOOLS) {
      expect(
        bulkBar[`resource_${tool}_one`],
        `missing access.json bulkBar.resource_${tool}_one`
      ).toBeTruthy();
      expect(
        bulkBar[`resource_${tool}_other`],
        `missing access.json bulkBar.resource_${tool}_other`
      ).toBeTruthy();
    }
  });

  it("initiative settings i18n covers every tool", () => {
    const detail = initiatives.detail as Record<string, string>;
    const groups = initiatives.settings.permissionGroups as Record<string, string>;
    const permissions = initiatives.settings.permissions as Record<string, string>;
    for (const tool of TOOLS) {
      const camel = toolCamelPlural(tool);
      const pascalPlural = `${toolPascalSingular(tool)}s`;
      expect(detail[camel], `missing initiatives.json detail.${camel}`).toBeTruthy();
      expect(
        groups[camel],
        `missing initiatives.json settings.permissionGroups.${camel}`
      ).toBeTruthy();
      expect(
        permissions[`view${pascalPlural}`],
        `missing initiatives.json settings.permissions.view${pascalPlural}`
      ).toBeTruthy();
      expect(
        permissions[`create${pascalPlural}`],
        `missing initiatives.json settings.permissions.create${pascalPlural}`
      ).toBeTruthy();
    }
    const featureKeys = initiatives as unknown as Record<string, string>;
    for (const tool of TOGGLEABLE_TOOLS) {
      const camel = toolCamelPlural(tool);
      expect(
        featureKeys[`${camel}Feature`],
        `missing initiatives.json ${camel}Feature`
      ).toBeTruthy();
      expect(
        featureKeys[`${camel}FeatureDescription`],
        `missing initiatives.json ${camel}FeatureDescription`
      ).toBeTruthy();
    }
  });
});

describe("tool routes", () => {
  // A tool's list IS its initiative tab, so the route lives inside the
  // initiative tree. Six sibling files rather than one dynamic $toolSegment
  // route: a dynamic segment beside `settings`/`apps` would resolve by
  // static-beats-dynamic ranking, which fails silently and only at runtime.
  it("every tool has its initiative tab route", () => {
    for (const tool of TOOLS) {
      const file = `${INITIATIVE_ROUTES}/${toolRouteSegment(tool)}/index.tsx`;
      expect(guildRouteFiles, `missing tab route file ${file}`).toContain(file);
    }
  });

  // Without this a tool could ship with a clickable card and nowhere to land.
  it("every tool has its per-entity detail route", () => {
    for (const tool of TOOLS) {
      const file = `${INITIATIVE_ROUTES}/${toolRouteSegment(tool)}/$${toolParamName(tool)}/index.tsx`;
      expect(guildRouteFiles, `missing detail route file ${file}`).toContain(file);
    }
  });

  // Every tool is renameable and deletable from its own settings page. The
  // absence of this check is how a tool shipped with no way to do either.
  it("every tool has its per-entity settings route", () => {
    for (const tool of TOOLS) {
      const file = `${INITIATIVE_ROUTES}/${toolRouteSegment(tool)}/$${toolParamName(tool)}/settings.tsx`;
      expect(guildRouteFiles, `missing settings route file ${file}`).toContain(file);
    }
  });

  // The tab routes are siblings of the initiative's own static children, so a
  // tool whose segment collided with one would be unreachable.
  it("no tool segment collides with a reserved initiative child route", () => {
    const reserved = new Set(["settings", "apps"]);
    for (const tool of TOOLS) {
      expect(
        reserved.has(toolRouteSegment(tool)),
        `${tool} would shadow /i/$initiativeId/${toolRouteSegment(tool)}`
      ).toBe(false);
    }
  });

  it("derives the route param name from the enum", () => {
    expect(toolCamelSingular(Tool.counter_group)).toBe("counterGroup");
    expect(toolParamName(Tool.counter_group)).toBe("counterGroupId");
    expect(toolParamName(Tool.project)).toBe("projectId");
  });
});

describe("tool route builders", () => {
  it("addresses a tool entity inside its initiative", () => {
    expect(toolListRoute(Tool.counter_group, 12)).toBe("/i/12/counter-groups");
    expect(toolDetailRoute(Tool.counter_group, 12, 3)).toBe("/i/12/counter-groups/3");
    expect(toolSettingsRoute(Tool.project, 1, 7)).toBe("/i/1/projects/7/settings");
  });

  // Only calendars have guild-level entities (an app installs one). A null
  // initiative means "address me at the guild route", never "unknown".
  it("keeps a guild-level entity at its guild route", () => {
    expect(toolListRoute(Tool.calendar, null)).toBe("/calendars");
    expect(toolDetailRoute(Tool.calendar, null, 3)).toBe("/calendars/3");
    expect(toolSettingsRoute(Tool.calendar, null, 3)).toBe("/calendars/3/settings");
  });

  it("nests a child entity under its parent", () => {
    expect(taskRoute(1, 2, 5)).toBe("/i/1/projects/2/tasks/5");
    expect(eventRoute(1, 2, 9)).toBe("/i/1/calendars/2/events/9");
    expect(eventRoute(null, 2, 9)).toBe("/calendars/2/events/9");
    expect(counterRoute(1, 3, 7)).toBe("/i/1/counter-groups/3/counter/7");
  });

  it("names the initiative tree", () => {
    expect(INITIATIVES_ROUTE).toBe("/i");
    expect(initiativeRoute(4)).toBe("/i/4");
  });

  it("routes a bare id through the resolver", () => {
    expect(entityRefRoute("document", 42)).toBe("/go/document/42");
    expect(toolRefRoute(Tool.counter_group, 3)).toBe("/go/counter-group/3");
  });
});

describe("tool surfaces", () => {
  it("every tool has a command-palette source", () => {
    expect(Object.keys(TOOL_PALETTE).sort()).toEqual(Object.values(Tool).sort());
    expect(PALETTE_TOOLS).toEqual(TOOLS);
  });

  // Generous timeout: importing the page pulls in the whole tab-view graph,
  // which can take over 30s on a slow machine while the full suite's workers
  // are all transforming concurrently.
  it("every tool has an initiative-detail tab view", { timeout: 60_000 }, async () => {
    const { TOOL_TAB_VIEWS } = await import("@/pages/InitiativeDetailPage");
    for (const tool of TOOLS) {
      expect(
        TOOL_TAB_VIEWS.get(tool),
        `missing InitiativeDetailPage tab view for ${tool}`
      ).toBeTruthy();
    }
  });
});

describe("tool exports", () => {
  it("every bulk-export tool has a format source, and only those", async () => {
    const { DOCUMENT_TYPE_FORMATS, TOOL_EXPORT_FORMATS } = await import(
      "@/components/exports/formats"
    );
    const { DocumentReadDocumentType } = await import("@/api/generated/initiativeAPI.schemas");
    const { BULK_EXPORT_TOOLS } = await import("@/lib/tools");

    for (const tool of BULK_EXPORT_TOOLS) {
      // Documents are per-type (their format set depends on the selection);
      // every document type must offer at least one engine format.
      if (tool === Tool.document) continue;
      expect(
        TOOL_EXPORT_FORMATS[tool]?.length,
        `missing TOOL_EXPORT_FORMATS[${tool}]`
      ).toBeGreaterThan(0);
    }
    for (const type of Object.values(DocumentReadDocumentType)) {
      expect(
        DOCUMENT_TYPE_FORMATS[type]?.length,
        `missing DOCUMENT_TYPE_FORMATS.${type}`
      ).toBeGreaterThan(0);
    }
    // Exact coverage: a formats entry for a non-export tool is drift too.
    for (const tool of TOOLS) {
      if (NON_EXPORTABLE_TOOLS.has(tool) && tool !== Tool.document) {
        expect(
          TOOL_EXPORT_FORMATS[tool],
          `${tool} declares formats but is in NON_EXPORTABLE_TOOLS`
        ).toBeUndefined();
      }
    }
  });

  it("derives the engine endpoint and selector params from the enum", async () => {
    const { toolExportEndpoint, toolExportIdParam, toolExportIdsParam } = await import(
      "@/lib/tools"
    );
    expect(toolExportEndpoint(Tool.counter_group)).toBe("/exports/counter-group");
    expect(toolExportEndpoint(Tool.document)).toBe("/exports/document");
    expect(toolExportIdParam(Tool.queue)).toBe("queue_id");
    expect(toolExportIdsParam(Tool.counter_group)).toBe("counter_group_ids");
  });
});

describe("tool imports", () => {
  // Export and import are one capability — a tool's JSON envelope round-trips
  // through both — so they share BULK_EXPORT_TOOLS rather than two sets that
  // could drift apart.
  it("round-trips the envelope type discriminator for every portable tool", async () => {
    const { BULK_EXPORT_TOOLS, toolEnvelopeType, toolForEnvelopeType } = await import(
      "@/lib/tools"
    );
    for (const tool of BULK_EXPORT_TOOLS) {
      expect(toolForEnvelopeType(toolEnvelopeType(tool))).toBe(tool);
    }
    // Every type is the kebab-singular now; a backup type maps to no tool.
    expect(toolEnvelopeType(Tool.calendar)).toBe("initiative-calendar");
    expect(toolForEnvelopeType("initiative-backup")).toBeNull();
  });
});
