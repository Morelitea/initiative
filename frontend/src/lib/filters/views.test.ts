import { describe, expect, it } from "vitest";

import {
  EMPTY_TASK_FILTERS,
  type TaskFilterSpec,
  taskFiltersEqual,
} from "@/lib/filters/taskFilters";
import { resolveViewState, type ViewLike } from "@/lib/filters/views";

const spec = (overrides: Partial<TaskFilterSpec> = {}): TaskFilterSpec => ({
  ...EMPTY_TASK_FILTERS,
  ...overrides,
});

const view = (
  slug: string,
  layout: string,
  filters: TaskFilterSpec = spec(),
  is_default = false
): ViewLike<TaskFilterSpec> => ({
  slug,
  is_default,
  filters,
  definition: { layout: { type: layout } },
});

const VIEWS: ViewLike<TaskFilterSpec>[] = [
  view("table", "table"),
  view("board", "board", spec(), true),
  view("incomplete", "table", spec({ status_categories: ["backlog", "todo", "in_progress"] })),
  view("mine", "table", spec({ assignees: ["me"] })),
];

const resolve = (
  args: Partial<
    Parameters<typeof resolveViewState<TaskFilterSpec, ViewLike<TaskFilterSpec>>>[0]
  > = {}
) =>
  resolveViewState({
    search: {},
    views: VIEWS,
    stored: null,
    emptySpec: EMPTY_TASK_FILTERS,
    equals: taskFiltersEqual,
    ...args,
  });

describe("resolveViewState", () => {
  it("opens on the default view, with its filters, on a first visit", () => {
    const result = resolve();

    expect(result.view?.slug).toBe("board");
    expect(result.spec).toEqual(EMPTY_TASK_FILTERS);
    expect(result.modified).toBe(false);
  });

  it("opens on the first view when none is the default", () => {
    expect(
      resolve({ views: VIEWS.map((view) => ({ ...view, is_default: false })) }).view?.slug
    ).toBe("table");
  });

  it("shows nothing and everything while there are no views yet", () => {
    const result = resolve({ views: [] });

    expect(result.view).toBeNull();
    expect(result.spec).toEqual(EMPTY_TASK_FILTERS);
  });

  it("prefers the view this person was last in over the default", () => {
    const result = resolve({ stored: { view: "mine", filters: {} } });

    expect(result.view?.slug).toBe("mine");
    expect(result.spec.assignees).toEqual(["me"]);
  });

  it("lets the URL win, so a link opens the same view for whoever opens it", () => {
    const result = resolve({
      search: { view: "incomplete" },
      stored: { view: "mine", filters: {} },
    });

    expect(result.view?.slug).toBe("incomplete");
    expect(result.spec.status_categories).toEqual(["backlog", "todo", "in_progress"]);
  });

  it("comes back to a view with this person's own filters for it", () => {
    const filters = { mine: spec({ assignees: ["me"], tag_ids: [9] }) };

    expect(resolve({ stored: { view: "mine", filters } })).toMatchObject({
      spec: { assignees: ["me"], tag_ids: [9] },
      modified: true,
    });
    // Their filters for one view never follow them into another.
    expect(resolve({ stored: { view: "incomplete", filters } })).toMatchObject({
      spec: { tag_ids: [] },
      modified: false,
    });
  });

  it("shows a view the URL names with its own filters, whatever this person keeps", () => {
    const result = resolve({
      search: { view: "mine" },
      stored: { view: "mine", filters: { mine: spec({ assignees: ["me"], tag_ids: [9] }) } },
    });

    expect(result.spec).toEqual(spec({ assignees: ["me"] }));
    expect(result.modified).toBe(false);
  });

  it("is not modified when this person's filters still match the view's", () => {
    const result = resolve({
      stored: { view: "mine", filters: { mine: spec({ assignees: ["me"] }) } },
    });

    expect(result.modified).toBe(false);
  });

  it("resolves a link from before views: a preset by slug, All as the default", () => {
    expect(resolve({ search: { preset: "mine" } }).view?.slug).toBe("mine");
    expect(resolve({ search: { preset: "all" } }).view?.slug).toBe("board");
    // A preset names filters, which only its view holds.
    expect(resolve({ search: { preset: "mine", view: "kanban" } }).view?.slug).toBe("mine");
  });

  it("opens an old layout link on that layout's first view with no filters", () => {
    // The shipped layout views took a suffix where a preset held their slug.
    const views = [
      view("mine", "table", spec({ assignees: ["me"] })),
      view("table-2", "table"),
      view("board-2", "board", spec(), true),
    ];

    expect(resolve({ views, search: { view: "table" } }).view?.slug).toBe("table-2");
    expect(resolve({ views, search: { view: "kanban" } }).view?.slug).toBe("board-2");
    expect(resolve({ views, search: { view: "calendar" } }).unresolvedView).toBe(true);
  });

  it("opens the view with the slug a link names before any old meaning of it", () => {
    const views = [
      view("table", "table", spec({ tag_ids: [3] })),
      view("board", "board", spec(), true),
      view("kanban", "board", spec({ assignees: ["me"] })),
      view("all", "table", spec({ due: "overdue" })),
    ];

    expect(resolve({ views, search: { view: "table" } }).view?.slug).toBe("table");
    expect(resolve({ views, search: { view: "kanban" } }).view?.slug).toBe("kanban");
    // A changed All kept its slug, so its old link opens it.
    expect(resolve({ views, search: { preset: "all" } }).view?.slug).toBe("all");
  });

  it("says so and carries on when the URL names a view that is gone", () => {
    const result = resolve({
      search: { view: "deleted-one" },
      stored: { view: "mine", filters: {} },
    });

    expect(result.unresolvedView).toBe(true);
    expect(result.view?.slug).toBe("mine");
  });

  it("does not call a view unresolved while the list is still loading", () => {
    expect(resolve({ search: { view: "mine" }, views: [] }).unresolvedView).toBe(false);
  });

  it("drops a remembered view the project no longer has", () => {
    expect(resolve({ stored: { view: "since-deleted", filters: {} } }).view?.slug).toBe("board");
  });
});
