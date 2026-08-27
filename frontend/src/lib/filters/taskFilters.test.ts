import { describe, expect, it } from "vitest";

import {
  ASSIGNEE_NONE,
  buildTaskConditions,
  buildTaskListParams,
  EMPTY_TASK_FILTERS,
  matchesDueWindow,
  specFromApi,
  type TaskFilterSpec,
  taskFilterCount,
  taskFiltersEqual,
} from "@/lib/filters/taskFilters";

const spec = (overrides: Partial<TaskFilterSpec> = {}): TaskFilterSpec => ({
  ...EMPTY_TASK_FILTERS,
  ...overrides,
});

const fields = (conditions: ReturnType<typeof buildTaskConditions>) =>
  conditions.map((c) => ("field" in c ? c.field : `group:${c.logic}`));

describe("buildTaskConditions", () => {
  it("always scopes to the project", () => {
    expect(buildTaskConditions(spec(), { projectId: 7 })).toEqual([
      { field: "project_id", op: "eq", value: 7 },
    ]);
  });

  it("filters by status category, never by status id, for a portable preset", () => {
    const conditions = buildTaskConditions(spec({ status_categories: ["backlog", "todo"] }), {
      projectId: 1,
    });

    expect(conditions).toContainEqual({
      field: "status_category",
      op: "in_",
      value: ["backlog", "todo"],
    });
    expect(fields(conditions)).not.toContain("task_status_id");
  });

  it("filters by status id when only named statuses are picked", () => {
    const conditions = buildTaskConditions(spec({ status_ids: [4, 5] }), { projectId: 1 });

    expect(conditions).toContainEqual({ field: "task_status_id", op: "in_", value: [4, 5] });
    expect(fields(conditions)).not.toContain("status_category");
  });

  it("widens rather than contradicts when both halves of the status filter are used", () => {
    // They are one control answering one question. ANDed, "Blocked" plus the
    // Done category would return nothing, since no task is both.
    const conditions = buildTaskConditions(spec({ status_ids: [4], status_categories: ["done"] }), {
      projectId: 1,
    });

    expect(conditions).toContainEqual({
      logic: "or",
      conditions: [
        { field: "task_status_id", op: "in_", value: [4] },
        { field: "status_category", op: "in_", value: ["done"] },
      ],
    });
  });

  it("compiles unassigned as is_null, which no id list can express", () => {
    const conditions = buildTaskConditions(spec({ assignees: [ASSIGNEE_NONE] }), {
      projectId: 1,
    });

    expect(conditions).toContainEqual({ field: "assignee_ids", op: "is_null", value: true });
  });

  it("compiles unassigned alongside real people as one OR group", () => {
    const conditions = buildTaskConditions(spec({ assignees: [ASSIGNEE_NONE, "me", "4"] }), {
      projectId: 1,
    });

    expect(conditions).toContainEqual({
      logic: "or",
      conditions: [
        { field: "assignee_ids", op: "is_null", value: true },
        { field: "assignee_ids", op: "in_", value: ["me", "4"] },
      ],
    });
  });

  it("keeps 'me' as a token so a shared link stays portable", () => {
    const conditions = buildTaskConditions(spec({ assignees: ["me"] }), { projectId: 1 });

    expect(conditions).toContainEqual({ field: "assignee_ids", op: "in_", value: ["me"] });
  });

  it("expands each due window to day-quantized bounds", () => {
    const midnight = new Date();
    midnight.setHours(0, 0, 0, 0);

    const overdue = buildTaskConditions(spec({ due: "overdue" }), { projectId: 1 });
    expect(overdue).toContainEqual({
      field: "due_date",
      op: "lt",
      value: midnight.toISOString(),
    });

    const today = buildTaskConditions(spec({ due: "today" }), { projectId: 1 });
    const group = today.find((c) => "logic" in c);
    expect(group).toBeDefined();
    expect(fields(today)).toEqual(["project_id", "group:and"]);
  });

  it("puts archived on the query param, not in conditions", () => {
    const params = buildTaskListParams(spec({ include_archived: true }), { projectId: 1 });

    expect(params.include_archived).toBe(true);
    expect(fields(params.conditions as never)).not.toContain("is_archived");
  });

  it("omits include_archived entirely when it is off", () => {
    const params = buildTaskListParams(spec(), { projectId: 1 });

    expect(params).not.toHaveProperty("include_archived");
  });

  it("produces deep-equal params across calls, so the loader's prefetch key matches", () => {
    // Regression guard: the route loader and the tasks section build their
    // params separately. A wall-clock due bound would differ between the two
    // calls and the prefetched entry would never be read.
    const full = spec({
      status_ids: [1, 2],
      status_categories: ["todo"],
      assignees: ["me", ASSIGNEE_NONE],
      tag_ids: [3],
      due: "7_days",
      include_archived: true,
    });

    expect(buildTaskListParams(full, { projectId: 9 })).toEqual(
      buildTaskListParams(full, { projectId: 9 })
    );
  });

  it("stays well inside the endpoint's condition limits when fully loaded", () => {
    const conditions = buildTaskConditions(
      spec({
        status_ids: Array.from({ length: 50 }, (_, i) => i),
        status_categories: ["backlog", "todo", "in_progress", "done"],
        assignees: [ASSIGNEE_NONE, ...Array.from({ length: 24 }, (_, i) => String(i))],
        tag_ids: Array.from({ length: 25 }, (_, i) => i),
        due: "30_days",
      }),
      { projectId: 1 }
    );

    // The endpoint caps leaves at 50 and group depth at 3.
    expect(conditions.length).toBeLessThanOrEqual(50);
    expect(conditions.every((c) => !("conditions" in c) || c.conditions.length <= 2)).toBe(true);
  });
});

describe("matchesDueWindow", () => {
  const iso = (offsetDays: number) => {
    const d = new Date();
    d.setHours(12, 0, 0, 0);
    d.setDate(d.getDate() + offsetDays);
    return d.toISOString();
  };

  it("admits everything when no window is set", () => {
    expect(matchesDueWindow(null, null)).toBe(true);
    expect(matchesDueWindow(iso(400), null)).toBe(true);
  });

  it("excludes a task with no due date once a window is set", () => {
    expect(matchesDueWindow(null, "today")).toBe(false);
  });

  it("agrees with the conditions sent to the server", () => {
    expect(matchesDueWindow(iso(-1), "overdue")).toBe(true);
    expect(matchesDueWindow(iso(0), "overdue")).toBe(false);
    expect(matchesDueWindow(iso(0), "today")).toBe(true);
    expect(matchesDueWindow(iso(1), "today")).toBe(false);
    expect(matchesDueWindow(iso(7), "7_days")).toBe(true);
    expect(matchesDueWindow(iso(8), "7_days")).toBe(false);
    expect(matchesDueWindow(iso(30), "30_days")).toBe(true);
    expect(matchesDueWindow(iso(31), "30_days")).toBe(false);
  });

  it("rejects an unparseable date rather than admitting it", () => {
    expect(matchesDueWindow("not-a-date", "today")).toBe(false);
  });
});

describe("specFromApi", () => {
  it("fills every field from a partial payload", () => {
    expect(specFromApi({ assignees: ["me"] })).toEqual(spec({ assignees: ["me"] }));
  });

  it("drops values of the wrong type rather than throwing", () => {
    expect(
      specFromApi({
        status_ids: ["nope"] as never,
        due: "next-week" as never,
        status_categories: ["invented"] as never,
      })
    ).toEqual(EMPTY_TASK_FILTERS);
  });

  it("treats a missing payload as no filters", () => {
    expect(specFromApi(null)).toEqual(EMPTY_TASK_FILTERS);
  });
});

describe("taskFiltersEqual / taskFilterCount", () => {
  it("counts each set filter, including archived", () => {
    expect(taskFilterCount(EMPTY_TASK_FILTERS)).toBe(0);
    expect(taskFilterCount(spec({ assignees: ["me"], due: "today", include_archived: true }))).toBe(
      3
    );
  });

  it("compares by value, so a tweaked preset is not equal to itself", () => {
    expect(taskFiltersEqual(spec({ tag_ids: [1] }), spec({ tag_ids: [1] }))).toBe(true);
    expect(taskFiltersEqual(spec({ tag_ids: [1] }), spec({ tag_ids: [1, 2] }))).toBe(false);
  });
});
