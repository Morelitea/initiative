import { describe, expect, it } from "vitest";

import type { InitiativeMemberRead } from "@/api/generated/initiativeAPI.schemas";
import { PermissionKey, Tool } from "@/api/generated/initiativeAPI.schemas";
import {
  ADVANCED_PERMISSION_GROUPS,
  ADVANCED_TOOL_PERMISSION_GROUP,
  CORE_PERMISSION_GROUPS,
  PERMISSION_LABEL_KEYS,
} from "@/hooks/useInitiativeRoles";

import {
  fullToolAccess,
  membershipToolAccess,
  readOnlyToolAccess,
  TOGGLEABLE_TOOLS,
  TOOL_BY_ID,
  TOOLS,
  toolIcon,
} from "./registry";

// Anti-drift guards for the tool registry. Types alone can't catch these: the
// registry's derived lookups (`TOOL_BY_ID`, the access maps, PERMISSION_LABEL_KEYS)
// are built with `Object.fromEntries` and typed as total `Record<Tool | PermissionKey, …>`,
// so a `Tool`/`PermissionKey` added to the backend-generated enum but forgotten
// in the `TOOLS` array compiles cleanly and only fails at runtime. These tests
// fail the build instead — the single place a new tool must be wired.

const ALL_TOOLS = Object.values(Tool);
const ALL_PERMISSION_KEYS = Object.values(PermissionKey);

describe("tool registry coverage", () => {
  it("has exactly one entry per backend Tool enum value", () => {
    expect(new Set(TOOLS.map((t) => t.id))).toEqual(new Set(ALL_TOOLS));
    // No duplicate ids.
    expect(TOOLS).toHaveLength(ALL_TOOLS.length);
    // TOOL_BY_ID resolves every tool (not a partial record masquerading as total).
    for (const tool of ALL_TOOLS) {
      expect(TOOL_BY_ID[tool]?.id).toBe(tool);
    }
  });

  it("maps every tool to an icon", () => {
    for (const tool of ALL_TOOLS) {
      expect(toolIcon(tool)).toBeTruthy();
    }
    // Unknown/non-tool entity types fall through so callers can default.
    expect(toolIcon("task")).toBeUndefined();
  });

  it("covers every PermissionKey exactly once across the tools' view/create keys", () => {
    const keys = TOOLS.flatMap((t) => [t.perm.view, t.perm.create]);
    expect(new Set(keys)).toEqual(new Set(ALL_PERMISSION_KEYS));
    // Each tool contributes two DISTINCT keys, and none collide across tools.
    expect(keys).toHaveLength(ALL_PERMISSION_KEYS.length);
  });
});

describe("derived permission structures stay in sync", () => {
  it("PERMISSION_LABEL_KEYS has a label for every PermissionKey", () => {
    for (const key of ALL_PERMISSION_KEYS) {
      expect(PERMISSION_LABEL_KEYS[key]).toBeTruthy();
    }
    expect(Object.keys(PERMISSION_LABEL_KEYS)).toHaveLength(ALL_PERMISSION_KEYS.length);
  });

  it("permission groups partition the tools by section", () => {
    const grouped = [
      ...CORE_PERMISSION_GROUPS,
      ...ADVANCED_PERMISSION_GROUPS,
      ADVANCED_TOOL_PERMISSION_GROUP,
    ];
    // One card per tool, each carrying its view + create key.
    expect(grouped).toHaveLength(TOOLS.length);
    const keysInGroups = grouped.flatMap((g) => g.keys);
    expect(new Set(keysInGroups)).toEqual(new Set(ALL_PERMISSION_KEYS));
    expect(CORE_PERMISSION_GROUPS).toHaveLength(TOOLS.filter((t) => t.section === "core").length);
    expect(ADVANCED_PERMISSION_GROUPS).toHaveLength(
      TOOLS.filter((t) => t.section === "advanced").length
    );
  });
});

describe("feature toggles", () => {
  it("TOGGLEABLE_TOOLS is exactly the tools with an enable flag, each with a toggle", () => {
    expect(TOGGLEABLE_TOOLS).toEqual(TOOLS.filter((t) => t.enableFlag !== null));
    for (const tool of TOGGLEABLE_TOOLS) {
      expect(tool.enableFlag).not.toBeNull();
      expect(tool.settingsToggle).toBeTruthy();
    }
    // Enable flags are unique (no two tools share one).
    const flags = TOGGLEABLE_TOOLS.map((t) => t.enableFlag);
    expect(new Set(flags).size).toBe(flags.length);
  });
});

describe("nav config", () => {
  it("every nav tool has a route + labels, and global-create implies a nav", () => {
    for (const tool of TOOLS) {
      if (tool.nav) {
        expect(tool.nav.listRoute.startsWith("/")).toBe(true);
        expect(tool.nav.labelKey).toBeTruthy();
        expect(tool.nav.createLabelKey).toBeTruthy();
      }
      // A tool can only be "create from anywhere" if it has a list route to open.
      if (tool.nav?.navCreateGlobal) {
        expect(tool.nav.listRoute).toBeTruthy();
      }
    }
  });
});

describe("access maps cover every tool", () => {
  const initiative = {
    queues_enabled: true,
    events_enabled: true,
    counters_enabled: true,
    advanced_tool_enabled: true,
  } as Parameters<typeof fullToolAccess>[0];

  it("fullToolAccess / readOnlyToolAccess return an entry for every tool", () => {
    const full = fullToolAccess(initiative, true);
    const readOnly = readOnlyToolAccess();
    for (const tool of ALL_TOOLS) {
      expect(full[tool]).toBeDefined();
      expect(readOnly[tool]).toBeDefined();
    }
    // Full access with all flags on ⇒ view+create everywhere.
    expect(ALL_TOOLS.every((t) => full[t].view && full[t].create)).toBe(true);
    // Read-only default ⇒ only always-on tools (no enable flag) are visible.
    for (const tool of TOOLS) {
      expect(readOnly[tool.id].view).toBe(tool.enableFlag === null);
      expect(readOnly[tool.id].create).toBe(false);
    }
  });

  it("membershipToolAccess resolves real membership fields for every tool", () => {
    // Every can_* set true — if a registry membership key were wrong, an
    // enable-flagged tool would resolve `undefined ?? false` and fail here.
    const membership = {
      can_view_docs: true,
      can_view_projects: true,
      can_view_queues: true,
      can_view_events: true,
      can_view_advanced_tool: true,
      can_view_counters: true,
      can_create_docs: true,
      can_create_projects: true,
      can_create_queues: true,
      can_create_events: true,
      can_create_advanced_tool: true,
      can_create_counters: true,
    } as unknown as InitiativeMemberRead;

    const access = membershipToolAccess(membership);
    for (const tool of ALL_TOOLS) {
      expect(access[tool].view).toBe(true);
      expect(access[tool].create).toBe(true);
    }
  });
});
