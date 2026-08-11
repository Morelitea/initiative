/**
 * The endpoint → widget contract.
 *
 * Worth testing directly because every widget on every dashboard reads these
 * shapes, and because the conversions here are exactly the ones a widget cannot
 * do for itself: it has a frozen clock and no timezone, so a date string that
 * reaches it is a bug this layer was supposed to catch.
 */
import { describe, expect, it } from "vitest";

import {
  countTasks,
  countTasksByProject,
  emptyDataFor,
  normalizeCalendarEntries,
  normalizeCounter,
  normalizeMyStats,
  normalizeProjects,
  normalizeSheetRange,
  normalizeTasks,
  startOfUtcDay,
  toEpoch,
} from "./normalize";

const task = (overrides: Record<string, unknown> = {}) =>
  ({
    id: 1,
    title: "Draft the spec",
    priority: "high",
    start_date: "2026-08-03T00:00:00Z",
    due_date: "2026-08-08T00:00:00Z",
    completed_at: null,
    project_id: 10,
    project_name: "Apollo",
    task_status: { name: "In review", category: "in_progress" },
    assignees: [{ id: 1, full_name: "Ada" }],
    ...overrides,
  }) as never;

describe("timestamps", () => {
  it("converts ISO strings to epoch ms", () => {
    expect(toEpoch("2026-08-03T00:00:00Z")).toBe(Date.UTC(2026, 7, 3));
  });

  it("returns null rather than NaN for absent or unparseable values", () => {
    expect(toEpoch(null)).toBeNull();
    expect(toEpoch(undefined)).toBeNull();
    expect(toEpoch("")).toBeNull();
    expect(toEpoch("not a date")).toBeNull();
  });

  it("buckets to UTC midnight", () => {
    const noon = Date.UTC(2026, 7, 3, 12, 30);
    expect(startOfUtcDay(noon)).toBe(Date.UTC(2026, 7, 3));
  });
});

describe("normalizeTasks", () => {
  it("hands widgets numbers, never date strings", () => {
    const [row] = normalizeTasks([task()]);
    expect(row.startDate).toBe(Date.UTC(2026, 7, 3));
    expect(row.dueDate).toBe(Date.UTC(2026, 7, 8));
    expect(row.completedAt).toBeNull();
    expect(typeof row.startDate).toBe("number");
  });

  it("flattens the status into name plus coarse category", () => {
    const [row] = normalizeTasks([task()]);
    expect(row.status).toBe("In review");
    expect(row.statusCategory).toBe("in_progress");
  });

  it("survives a task with nothing optional set", () => {
    const [row] = normalizeTasks([
      task({
        priority: null,
        start_date: null,
        due_date: null,
        project_id: null,
        project_name: null,
        task_status: null,
        assignees: null,
      }),
    ]);
    expect(row).toMatchObject({
      priority: null,
      startDate: null,
      projectName: null,
      statusCategory: "todo",
      assignees: [],
    });
  });
});

describe("countTasks", () => {
  const tasks = normalizeTasks([
    task({ id: 1, task_status: { name: "To do", category: "todo" } }),
    task({ id: 2, task_status: { name: "To do", category: "todo" } }),
    task({
      id: 3,
      task_status: { name: "Done", category: "done" },
      completed_at: "2026-08-05T09:00:00Z",
    }),
  ]);

  it("groups by status category by default", () => {
    expect(countTasks(tasks)).toEqual([
      { bucket: "todo", count: 2 },
      { bucket: "done", count: 1 },
    ]);
  });

  it("groups by day only over completions, which are the only dated events", () => {
    const rows = countTasks(tasks, "day");
    expect(rows).toHaveLength(1);
    expect(rows[0]).toMatchObject({ bucket: "2026-08-05", count: 1 });
    expect(rows[0].date).toBe(Date.UTC(2026, 7, 5));
  });

  it("counts a task once per assignee when grouping by assignee", () => {
    const shared = normalizeTasks([
      task({
        assignees: [
          { id: 1, full_name: "Ada" },
          { id: 2, full_name: "Grace" },
        ],
      }),
    ]);
    expect(countTasks(shared, "assignee")).toEqual([
      { bucket: "Ada", count: 1 },
      { bucket: "Grace", count: 1 },
    ]);
  });

  it("labels the absent cases rather than dropping them", () => {
    const orphan = normalizeTasks([task({ project_name: null, assignees: [] })]);
    expect(countTasks(orphan, "project")).toEqual([{ bucket: "Unassigned", count: 1 }]);
    expect(countTasks(orphan, "assignee")).toEqual([{ bucket: "Unassigned", count: 1 }]);
  });
});

describe("normalizeProjects", () => {
  const project = {
    id: 10,
    name: "Apollo",
    start_date: "2026-08-03T00:00:00Z",
    end_date: null,
  } as never;

  it("derives progress from the task counts it was given", () => {
    const counts = countTasksByProject(
      normalizeTasks([
        task({ id: 1 }),
        task({ id: 2, task_status: { name: "Done", category: "done" } }),
      ])
    );
    const [row] = normalizeProjects([project], counts);
    expect(row).toMatchObject({ taskCount: 2, doneCount: 1, progress: 0.5 });
  });

  it("reads as zero rather than guessing when no counts are supplied", () => {
    const [row] = normalizeProjects([project]);
    expect(row).toMatchObject({ taskCount: 0, doneCount: 0, progress: 0 });
  });
});

describe("normalizeCalendarEntries", () => {
  const event = (overrides: Record<string, unknown> = {}) =>
    ({
      id: 100,
      title: "Kickoff",
      start_at: "2026-08-04T09:00:00Z",
      end_at: "2026-08-04T10:00:00Z",
      all_day: false,
      calendar_id: 5,
      ...overrides,
    }) as never;

  it("resolves calendar names from the calendars query", () => {
    const [row] = normalizeCalendarEntries([event()], new Map([[5, "Team"]]));
    expect(row.calendarName).toBe("Team");
  });

  it("gives an event with no end a visible width", () => {
    const [row] = normalizeCalendarEntries([event({ end_at: null })]);
    expect(row.end).toBeGreaterThan(row.start);
  });

  it("drops an event with no usable start rather than placing it at zero", () => {
    expect(normalizeCalendarEntries([event({ start_at: null })])).toHaveLength(0);
  });
});

describe("normalizeCounter", () => {
  it("parses the decimal strings counters are stored as", () => {
    const counter = normalizeCounter({
      name: "Beds",
      count: "34",
      min: "0",
      max: "50",
    } as never);
    expect(counter).toMatchObject({ value: 34, min: 0, max: 50 });
  });

  it("keeps an open-ended counter's null bounds null", () => {
    const counter = normalizeCounter({
      name: "Signups",
      count: "7",
      min: null,
      max: null,
    } as never);
    expect(counter.min).toBeNull();
    expect(counter.max).toBeNull();
  });
});

describe("normalizeMyStats", () => {
  it("maps heatmap days to epoch dates", () => {
    const { days, total } = normalizeMyStats({
      heatmap_data: [{ date: "2026-08-03", activity_count: 4 }],
      tasks_completed_total: 112,
    } as never);
    expect(days).toEqual([{ date: Date.UTC(2026, 7, 3), count: 4 }]);
    expect(total).toBe(112);
  });

  it("survives a stats payload with no heatmap", () => {
    expect(normalizeMyStats({} as never)).toEqual({ days: [], total: 0 });
  });
});

describe("normalizeSheetRange", () => {
  const doc = (cells: Record<string, unknown>, name = "Sheet1") =>
    ({ content: { sheets: [{ id: "s1", name, cells }] } }) as never;

  it("extracts an A1 range in row-major order", () => {
    const range = normalizeSheetRange(
      doc({ "0:0": "Stage", "0:1": "Count", "1:0": "Leads", "1:1": 100 }),
      "Sheet1",
      "A1:B2"
    );
    expect(range).toEqual({ columns: ["Stage", "Count"], rows: [["Leads", 100]] });
  });

  it("treats an all-text first row as headers only when rows follow", () => {
    const range = normalizeSheetRange(doc({ "0:0": "Only", "0:1": "Headers" }), null, "A1:B1");
    expect(range?.columns).toEqual(["Column 1", "Column 2"]);
    expect(range?.rows).toEqual([["Only", "Headers"]]);
  });

  it("nulls a cell holding anything that is not a scalar", () => {
    const range = normalizeSheetRange(doc({ "0:0": { nested: true } }), null, "A1");
    expect(range?.rows).toEqual([[null]]);
  });

  it("returns null for an unusable binding rather than throwing", () => {
    expect(normalizeSheetRange(doc({}), "Nope", "A1")).toBeNull();
    expect(normalizeSheetRange(doc({}), "Sheet1", "not-a-range")).toBeNull();
    expect(normalizeSheetRange({ content: null } as never, null, "A1")).toBeNull();
  });
});

describe("emptyDataFor", () => {
  it("produces a valid envelope for every source", () => {
    const sources = [
      "tasks",
      "projects",
      "calendar_entries",
      "task_counts",
      "counter",
      "counter_group",
      "my_stats",
      "sheet_range",
    ] as const;
    for (const source of sources) {
      expect(emptyDataFor(source).source).toBe(source);
    }
  });
});
