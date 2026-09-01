/**
 * Where a search result goes.
 *
 * A hit carries its initiative and the tool it lives in precisely so the page
 * can build the address without a round trip — which means a wrong rule here is
 * a link that lands on the wrong thing, or on nothing, with nothing else to
 * catch it.
 */
import fs from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

import { Tool } from "@/api/generated/initiativeAPI.schemas";
import {
  hitCategory,
  type SearchTarget,
  searchHitPath,
  TAG_ENTITY_TYPE,
  TOOL_ENTITY_TYPES,
} from "@/lib/searchResults";
import { TOOLS } from "@/lib/tools";

const target = (overrides: Partial<SearchTarget> & Pick<SearchTarget, "entity_type">) =>
  ({ entity_id: 1, initiative_id: 5, tool: null, tool_id: null, ...overrides }) as SearchTarget;

describe("searchHitPath", () => {
  it("addresses a tool's own row inside its initiative", () => {
    expect(
      searchHitPath(
        target({ entity_type: "project", entity_id: 7, tool: Tool.project, tool_id: 7 })
      )
    ).toBe("/i/5/projects/7");
    expect(
      searchHitPath(
        target({ entity_type: "dashboard", entity_id: 3, tool: Tool.dashboard, tool_id: 3 })
      )
    ).toBe("/i/5/dashboards/3");
  });

  it("nests a child under the tool it lives in", () => {
    expect(
      searchHitPath(target({ entity_type: "task", entity_id: 22, tool: Tool.project, tool_id: 7 }))
    ).toBe("/i/5/projects/7/tasks/22");
    expect(
      searchHitPath(
        target({ entity_type: "calendar_event", entity_id: 8, tool: Tool.calendar, tool_id: 2 })
      )
    ).toBe("/i/5/calendars/2/events/8");
    expect(
      searchHitPath(
        target({ entity_type: "counter", entity_id: 9, tool: Tool.counter_group, tool_id: 6 })
      )
    ).toBe("/i/5/counter-groups/6/counter/9");
  });

  it("sends a queue item to its queue, which is where it is read", () => {
    expect(
      searchHitPath(
        target({ entity_type: "queue_item", entity_id: 4, tool: Tool.queue, tool_id: 2 })
      )
    ).toBe("/i/5/queues/2");
  });

  it("gives a tag the guild address it has — tags belong to no initiative", () => {
    expect(searchHitPath(target({ entity_type: TAG_ENTITY_TYPE, entity_id: 12 }))).toBe("/tags/12");
  });

  it("keeps a guild-level entity on its guild route", () => {
    // An app-installed calendar has no initiative; `null` means "address me at
    // the guild route", not "initiative unknown".
    expect(
      searchHitPath(
        target({
          entity_type: "calendar",
          entity_id: 2,
          initiative_id: null,
          tool: Tool.calendar,
          tool_id: 2,
        })
      )
    ).toBe("/calendars/2");
  });

  it("has no address for a hit that names no tool", () => {
    expect(
      searchHitPath(target({ entity_type: "task", entity_id: 1, tool: Tool.project }))
    ).toBeNull();
    expect(searchHitPath(target({ entity_type: "project", entity_id: 1 }))).toBeNull();
  });
});

describe("categories", () => {
  it("puts everything but the guild's vocabulary under tools", () => {
    for (const entityType of TOOL_ENTITY_TYPES) {
      expect(hitCategory(target({ entity_type: entityType }))).toBe("tool");
    }
    expect(hitCategory(target({ entity_type: TAG_ENTITY_TYPE }))).toBe("tag");
  });

  it("covers every tool, so a new one is searchable without an edit here", () => {
    for (const tool of TOOLS) {
      expect(TOOL_ENTITY_TYPES).toContain(tool);
    }
  });
});

describe("labels", () => {
  const labels = JSON.parse(
    fs.readFileSync(path.resolve(__dirname, "../../public/locales/en/search.json"), "utf-8")
  ).types as Record<string, string>;

  it("names every kind of result a reader can be shown", () => {
    for (const entityType of [...TOOL_ENTITY_TYPES, TAG_ENTITY_TYPE]) {
      expect(labels[entityType], `search.json is missing types.${entityType}`).toBeTruthy();
    }
  });
});
