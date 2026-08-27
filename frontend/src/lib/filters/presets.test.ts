import { describe, expect, it } from "vitest";

import { resolvePresetState } from "@/lib/filters/presets";
import {
  EMPTY_TASK_FILTERS,
  TASK_VIEW_MODES,
  type TaskFilterSpec,
  type TaskViewMode,
  taskFiltersEqual,
} from "@/lib/filters/taskFilters";

const spec = (overrides: Partial<TaskFilterSpec> = {}): TaskFilterSpec => ({
  ...EMPTY_TASK_FILTERS,
  ...overrides,
});

const PRESETS = [
  { slug: "all", is_default: true, filters: spec() },
  {
    slug: "incomplete",
    is_default: false,
    filters: spec({ status_categories: ["backlog", "todo", "in_progress"] }),
  },
  { slug: "mine", is_default: false, filters: spec({ assignees: ["me"] }) },
];

const resolve = (
  args: Partial<Parameters<typeof resolvePresetState<TaskFilterSpec, TaskViewMode>>[0]> = {}
) =>
  resolvePresetState<TaskFilterSpec, TaskViewMode>({
    search: {},
    presets: PRESETS,
    stored: null,
    allowedViews: TASK_VIEW_MODES,
    defaultView: null,
    fallbackView: "table",
    emptySpec: EMPTY_TASK_FILTERS,
    equals: taskFiltersEqual,
    ...args,
  });

describe("resolvePresetState", () => {
  it("falls back to the project's default preset and view on a first visit", () => {
    const result = resolve({ defaultView: "kanban" });

    expect(result.activeSlug).toBe("all");
    expect(result.viewMode).toBe("kanban");
    expect(result.spec).toEqual(EMPTY_TASK_FILTERS);
  });

  it("falls back to everything in the first view with no default at all", () => {
    const result = resolve({ presets: [] });

    expect(result.activeSlug).toBeNull();
    expect(result.viewMode).toBe("table");
    expect(result.spec).toEqual(EMPTY_TASK_FILTERS);
  });

  it("prefers what this person last had over the project default", () => {
    const result = resolve({
      stored: { spec: spec({ tag_ids: [4] }), viewMode: "calendar", activePresetSlug: null },
      defaultView: "kanban",
    });

    expect(result.spec.tag_ids).toEqual([4]);
    expect(result.viewMode).toBe("calendar");
    expect(result.activeSlug).toBeNull();
  });

  it("lets the URL win over both, so a link means the same for whoever opens it", () => {
    const result = resolve({
      search: { preset: "mine", view: "kanban" },
      stored: { spec: spec({ tag_ids: [4] }), viewMode: "calendar", activePresetSlug: null },
      defaultView: "table",
    });

    expect(result.activeSlug).toBe("mine");
    expect(result.spec.assignees).toEqual(["me"]);
    expect(result.viewMode).toBe("kanban");
  });

  it("treats view and preset as independent axes", () => {
    expect(resolve({ search: { view: "calendar" } })).toMatchObject({
      viewMode: "calendar",
      activeSlug: "all",
    });
    expect(resolve({ search: { preset: "incomplete" } })).toMatchObject({
      viewMode: "table",
      activeSlug: "incomplete",
    });
  });

  it("says so and carries on when the URL names a preset that is gone", () => {
    const result = resolve({ search: { preset: "deleted-one" }, defaultView: "kanban" });

    expect(result.unresolvedPreset).toBe(true);
    expect(result.activeSlug).toBe("all");
    expect(result.viewMode).toBe("kanban");
  });

  it("does not call a preset unresolved while the list is still loading", () => {
    const result = resolve({ search: { preset: "mine" }, presets: [] });

    expect(result.unresolvedPreset).toBe(false);
  });

  it("reports a remembered preset as modified once its values were tweaked", () => {
    const result = resolve({
      stored: {
        spec: spec({ assignees: ["me"], tag_ids: [9] }),
        activePresetSlug: "mine",
      },
    });

    expect(result.activeSlug).toBe("mine");
    expect(result.modified).toBe(true);
  });

  it("is not modified when the remembered values still match the preset", () => {
    const result = resolve({
      stored: { spec: spec({ assignees: ["me"] }), activePresetSlug: "mine" },
    });

    expect(result.activeSlug).toBe("mine");
    expect(result.modified).toBe(false);
  });

  it("drops a remembered slug the project no longer has", () => {
    const result = resolve({
      stored: { spec: spec({ tag_ids: [1] }), activePresetSlug: "since-deleted" },
    });

    expect(result.activeSlug).toBeNull();
    expect(result.modified).toBe(false);
    expect(result.spec.tag_ids).toEqual([1]);
  });

  it("ignores a view mode outside the tool's vocabulary", () => {
    expect(resolve({ search: { view: "gantt" }, defaultView: "kanban" }).viewMode).toBe("kanban");
    expect(resolve({ defaultView: "gantt" }).viewMode).toBe("table");
  });

  it("ignores a malformed preset slug", () => {
    expect(resolve({ search: { preset: "Not A Slug!" } }).activeSlug).toBe("all");
    expect(resolve({ search: { preset: "Not A Slug!" } }).unresolvedPreset).toBe(false);
  });
});
