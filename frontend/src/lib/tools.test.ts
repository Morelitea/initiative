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
  PermissionKey,
  RecentEntityType,
  Tool,
  TrashItemEntityType,
} from "@/api/generated/initiativeAPI.schemas";
import { PALETTE_TOOLS, TOOL_PALETTE } from "@/lib/toolPalette";
import {
  RECENTABLE_TOOLS,
  SIDEBAR_TOOLS,
  TOGGLEABLE_TOOLS,
  TOOL_REGISTRY,
  TOOLS,
  toolCamelPlural,
  toolCreateLabelKey,
  toolCreatePermission,
  toolNavLabelKey,
  toolPascalSingular,
  toolRouteSegment,
  toolViewPermission,
} from "@/lib/tools";

import access from "../../public/locales/en/access.json";
import command from "../../public/locales/en/command.json";
import initiatives from "../../public/locales/en/initiatives.json";
import nav from "../../public/locales/en/nav.json";
import trash from "../../public/locales/en/trash.json";

// Route files (keys only — nothing is loaded). The guild tree holds each
// tool's list route; the top-level tree holds the personal pages.
const guildRouteFiles = Object.keys(
  import.meta.glob("../routes/_serverRequired/_authenticated/g/$guildId/*.tsx")
);
const personalRouteFiles = Object.keys(
  import.meta.glob("../routes/_serverRequired/_authenticated/*.tsx")
);
// Locale namespace files across every shipped language.
const localeFiles = Object.keys(import.meta.glob("../../public/locales/*/*.json"));
const locales = [...new Set(localeFiles.map((f) => f.split("/").at(-2)))];

describe("tool registry", () => {
  it("covers exactly the canonical Tool enum", () => {
    expect(Object.keys(TOOL_REGISTRY).sort()).toEqual(Object.values(Tool).sort());
  });

  it("sidebar order is a permutation of the tools", () => {
    expect([...SIDEBAR_TOOLS].sort()).toEqual([...TOOLS].sort());
  });

  it("derives the exact permission keys the API exposes", () => {
    const derived = TOOLS.flatMap((tool) => [toolViewPermission(tool), toolCreatePermission(tool)]);
    expect(derived.sort()).toEqual(Object.values(PermissionKey).sort());
  });

  it("recents capability mirrors the backend's recentable set", () => {
    expect(RECENTABLE_TOOLS.map(String).sort()).toEqual(Object.values(RecentEntityType).sort());
  });

  it("every tool is a trash entity type with a label", () => {
    const trashTypes = Object.values(TrashItemEntityType) as string[];
    const labels = trash.entityType as Record<string, string>;
    for (const tool of TOOLS) {
      expect(trashTypes, `missing TrashItemEntityType for ${tool}`).toContain(tool);
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
  it("every tool with an in-app collection has its guild list route", () => {
    for (const tool of TOOLS) {
      if (tool === Tool.advanced_tool) continue; // embedded per-initiative page instead
      const file = `../routes/_serverRequired/_authenticated/g/$guildId/${toolRouteSegment(tool)}.tsx`;
      expect(guildRouteFiles, `missing route file ${file}`).toContain(file);
    }
    // The advanced tool's embedded pages (initiative + guild settings).
    expect(
      guildRouteFiles.some((f) => f.includes("advanced-tool")),
      "missing advanced-tool route under /g/$guildId"
    ).toBe(true);
  });

  it("declared personal routes exist", () => {
    for (const tool of TOOLS) {
      const personalRoute = TOOL_REGISTRY[tool].personalRoute;
      if (!personalRoute) continue;
      const file = `../routes/_serverRequired/_authenticated/${personalRoute.slice(1)}.tsx`;
      expect(personalRouteFiles, `missing personal route file ${file}`).toContain(file);
    }
  });
});

describe("tool surfaces", () => {
  it("every tool has a command-palette source", () => {
    expect(Object.keys(TOOL_PALETTE).sort()).toEqual(Object.values(Tool).sort());
    expect(PALETTE_TOOLS).toEqual(TOOLS.filter((tool) => TOOL_REGISTRY[tool].commandPalette));
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
      if (!TOOL_REGISTRY[tool].bulkExport && tool !== Tool.document) {
        expect(
          TOOL_EXPORT_FORMATS[tool],
          `${tool} declares formats but bulkExport is false`
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
  it("importable tools are exactly the bulk-export tools", async () => {
    const { IMPORTABLE_TOOLS, BULK_EXPORT_TOOLS } = await import("@/lib/tools");
    expect([...IMPORTABLE_TOOLS].sort()).toEqual([...BULK_EXPORT_TOOLS].sort());
  });

  it("round-trips the envelope type discriminator for every importable tool", async () => {
    const { IMPORTABLE_TOOLS, toolEnvelopeType, toolForEnvelopeType } = await import("@/lib/tools");
    for (const tool of IMPORTABLE_TOOLS) {
      expect(toolForEnvelopeType(toolEnvelopeType(tool))).toBe(tool);
    }
    // Calendar events are the plural exception; a backup type maps to no tool.
    expect(toolEnvelopeType(Tool.calendar_event)).toBe("initiative-calendar-events");
    expect(toolForEnvelopeType("initiative-backup")).toBeNull();
  });
});
