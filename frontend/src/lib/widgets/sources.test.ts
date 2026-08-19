import { describe, expect, it } from "vitest";

import type { WidgetBinding } from "@/hooks/useWidgetData";
import type { WidgetSource } from "@/lib/widgets/dataShapes";
import {
  acceptsFilters,
  effectiveBucket,
  entityParams,
  SOURCES,
  unboundSlots,
} from "@/lib/widgets/sources";

const binding = (partial: Partial<WidgetBinding> & { source: WidgetSource }): WidgetBinding =>
  partial as WidgetBinding;

describe("the source registry", () => {
  it("describes every source the data shapes declare", () => {
    // The registry is what the config dialog, the provenance line and
    // unboundSlots all read, so a source missing here has no controls and no
    // description anywhere.
    const declared = Object.keys(SOURCES).sort();
    expect(declared).toEqual(
      [
        "app",
        "calendar_entries",
        "counter",
        "counter_group",
        "projects",
        "sheet_range",
        "task_counts",
        "tasks",
      ].sort()
    );
  });

  it("gives every source a row noun for its counts and empty states", () => {
    for (const descriptor of Object.values(SOURCES)) {
      expect(descriptor.rowNoun).toBeTruthy();
    }
  });
});

describe("unboundSlots", () => {
  it("is empty for a source whose parameters are all optional", () => {
    expect(unboundSlots(binding({ source: "tasks" }))).toEqual([]);
    expect(unboundSlots(binding({ source: "projects" }))).toEqual([]);
  });

  it("names both halves of a counter binding until each is filled", () => {
    expect(unboundSlots(binding({ source: "counter" }))).toEqual([
      "counter_group_id",
      "counter_id",
    ]);
    expect(unboundSlots(binding({ source: "counter", counter_group_id: 3 }))).toEqual([
      "counter_id",
    ]);
    expect(
      unboundSlots(binding({ source: "counter", counter_group_id: 3, counter_id: 9 }))
    ).toEqual([]);
  });

  it("treats a sheet's name as optional and its range as required", () => {
    expect(unboundSlots(binding({ source: "sheet_range", document_id: 1 }))).toEqual(["range"]);
    expect(
      unboundSlots(binding({ source: "sheet_range", document_id: 1, range: "A1:B2" }))
    ).toEqual([]);
  });

  it("names an app binding's two slots", () => {
    expect(unboundSlots(binding({ source: "app" }))).toEqual(["app_uid", "source_id"]);
  });
});

describe("entityParams", () => {
  it("lists the ids a source can point at, in the order they are chosen", () => {
    expect(entityParams("counter").map((param) => param.key)).toEqual([
      "counter_group_id",
      "counter_id",
    ]);
  });

  it("marks the counter as living inside its group, so the picker can wait", () => {
    const [, counter] = entityParams("counter");
    expect(counter.within).toBe("counter_group_id");
  });

  it("is empty for a source with no ids", () => {
    expect(entityParams("projects")).toEqual([]);
  });
});

describe("acceptsFilters", () => {
  it("is true for the task-backed sources and false for a single counter", () => {
    expect(acceptsFilters("tasks")).toBe(true);
    expect(acceptsFilters("task_counts")).toBe(true);
    expect(acceptsFilters("projects")).toBe(true);
    expect(acceptsFilters("counter")).toBe(false);
  });
});

describe("effectiveBucket", () => {
  it("falls back to the declared default rather than to nothing", () => {
    expect(effectiveBucket(binding({ source: "task_counts" }))).toBe("status_category");
  });

  it("keeps a bucket the source declares", () => {
    expect(effectiveBucket(binding({ source: "task_counts", bucket: "day" }))).toBe("day");
  });

  it("ignores a bucket the source does not declare", () => {
    expect(effectiveBucket(binding({ source: "task_counts", bucket: "nonsense" } as never))).toBe(
      "status_category"
    );
  });

  it("is undefined for a source that does not bucket", () => {
    expect(effectiveBucket(binding({ source: "tasks" }))).toBeUndefined();
  });
});
