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
  NON_EXPORTABLE_TOOLS,
  SIDEBAR_TOOLS,
  TOGGLEABLE_TOOLS,
  TOOL_ICONS,
  TOOLS,
  toolCamelPlural,
  toolCamelSingular,
  toolCreateLabelKey,
  toolCreatePermission,
  toolNavLabelKey,
  toolParamName,
  toolPascalSingular,
  toolRouteSegment,
  toolViewPermission,
} from "@/lib/tools";

import access from "../../public/locales/en/access.json";
import command from "../../public/locales/en/command.json";
import guildHome from "../../public/locales/en/guildHome.json";
import initiatives from "../../public/locales/en/initiatives.json";
import nav from "../../public/locales/en/nav.json";
import trash from "../../public/locales/en/trash.json";

// Route files (keys only — nothing is loaded). The guild tree holds each
// tool's list, detail, and settings routes.
const guildRouteFiles = Object.keys(
  import.meta.glob("../routes/_serverRequired/_authenticated/g/$guildId/*.tsx")
);
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
  it("every tool has its guild list route", () => {
    for (const tool of TOOLS) {
      const file = `../routes/_serverRequired/_authenticated/g/$guildId/${toolRouteSegment(tool)}.tsx`;
      expect(guildRouteFiles, `missing route file ${file}`).toContain(file);
    }
  });

  it("derives the route param name from the enum", () => {
    expect(toolCamelSingular(Tool.counter_group)).toBe("counterGroup");
    expect(toolParamName(Tool.counter_group)).toBe("counterGroupId");
    expect(toolParamName(Tool.project)).toBe("projectId");
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
