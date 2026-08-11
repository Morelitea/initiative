/**
 * Sample data in the shapes `dataShapes.ts` documents.
 *
 * The fetchers that will produce these for real land with the canvas (Phase
 * 2b); until then these are what the built-ins are developed and tested
 * against, and what the dev route draws. Keeping them in one place means the
 * contract is exercised rather than assumed.
 */

import type { WidgetData, WidgetSource } from "../dataShapes";

const DAY = 86_400_000;
/** A fixed anchor — the widgets get a frozen clock, so fixtures get a frozen
 *  calendar. Renders stay byte-identical across runs. */
const T0 = Date.UTC(2026, 7, 3);

export interface WidgetFixture {
  source: WidgetSource;
  data: WidgetData;
  /** The same source with nothing in it — the "no data yet" path every widget
   *  has to survive. */
  empty: WidgetData;
  /** Per-widget shape of the same source, where one source legitimately has
   *  more than one. `task_counts` is the case that forces this: grouped by
   *  status it feeds a chart or a funnel, grouped by day it feeds a heatmap,
   *  and neither grouping can stand in for the other. */
  variants?: Record<string, WidgetData>;
}

const tasks: WidgetFixture = {
  source: "tasks",
  data: {
    source: "tasks",
    rows: [
      {
        id: 1,
        title: "Draft the spec",
        status: "In review",
        statusCategory: "in_progress",
        priority: "high",
        startDate: T0,
        dueDate: T0 + 5 * DAY,
        completedAt: null,
        projectId: 10,
        projectName: "Apollo",
        assignees: ["Ada"],
      },
      {
        id: 2,
        title: "Ship the migration",
        status: "Done",
        statusCategory: "done",
        priority: "medium",
        startDate: T0 + 2 * DAY,
        dueDate: T0 + 6 * DAY,
        completedAt: T0 + 6 * DAY,
        projectId: 10,
        projectName: "Apollo",
        assignees: ["Grace", "Ada"],
      },
      {
        id: 3,
        title: "Chase the vendor",
        status: "Blocked",
        statusCategory: "todo",
        priority: null,
        startDate: null,
        dueDate: T0 + 1 * DAY,
        completedAt: null,
        projectId: null,
        projectName: null,
        assignees: [],
      },
    ],
  },
  empty: { source: "tasks", rows: [] },
};

const projects: WidgetFixture = {
  source: "projects",
  data: {
    source: "projects",
    rows: [
      {
        id: 10,
        name: "Apollo",
        startDate: T0,
        endDate: T0 + 30 * DAY,
        progress: 0.4,
        taskCount: 20,
        doneCount: 8,
      },
      {
        id: 11,
        name: "Borealis",
        startDate: T0 + 10 * DAY,
        endDate: T0 + 45 * DAY,
        progress: 1,
        taskCount: 12,
        doneCount: 12,
      },
    ],
  },
  empty: { source: "projects", rows: [] },
};

const calendarEntries: WidgetFixture = {
  source: "calendar_entries",
  data: {
    source: "calendar_entries",
    rows: [
      {
        id: 100,
        title: "Kickoff",
        start: T0 + DAY,
        end: T0 + DAY + 3_600_000,
        calendarName: "Team",
        allDay: false,
      },
      {
        id: 101,
        title: "Retro",
        start: T0 + 8 * DAY,
        end: T0 + 8 * DAY + 3_600_000,
        calendarName: "Team",
        allDay: false,
      },
    ],
  },
  empty: { source: "calendar_entries", rows: [] },
};

const taskCounts: WidgetFixture = {
  source: "task_counts",
  data: {
    source: "task_counts",
    rows: [
      { bucket: "todo", count: 12 },
      { bucket: "in_progress", count: 5 },
      { bucket: "done", count: 23 },
    ],
  },
  empty: { source: "task_counts", rows: [] },
  variants: {
    // Grouped by day rather than status — the only grouping with a calendar
    // shape, and the one a heatmap binding would ask for.
    heatmap: {
      source: "task_counts",
      rows: Array.from({ length: 21 }, (_, index) => ({
        bucket: new Date(T0 + index * DAY).toISOString().slice(0, 10),
        count: (index * 5) % 7,
        date: T0 + index * DAY,
      })),
    },
  },
};

const counter: WidgetFixture = {
  source: "counter",
  data: {
    source: "counter",
    counter: { name: "Beds made", value: 34, min: 0, max: 50, unit: "beds" },
  },
  // A counter with no ceiling is the interesting empty-ish case: progress has
  // no denominator to draw, while the KPI is perfectly happy.
  empty: {
    source: "counter",
    counter: { name: "Signups", value: 0, min: null, max: null, unit: null },
  },
};

const counterGroup: WidgetFixture = {
  source: "counter_group",
  data: {
    source: "counter_group",
    name: "Inventory",
    counters: [
      { name: "Widgets", value: 120, min: 0, max: null, unit: "units" },
      { name: "Gadgets", value: 64, min: 0, max: null, unit: "units" },
      { name: "Doodads", value: 12, min: 0, max: null, unit: "units" },
    ],
  },
  empty: { source: "counter_group", name: "Inventory", counters: [] },
};

const myStats: WidgetFixture = {
  source: "my_stats",
  data: {
    source: "my_stats",
    days: Array.from({ length: 28 }, (_, index) => ({
      date: T0 + index * DAY,
      count: (index * 7) % 9,
    })),
    total: 112,
  },
  empty: { source: "my_stats", days: [], total: 0 },
};

const sheetRange: WidgetFixture = {
  source: "sheet_range",
  data: {
    source: "sheet_range",
    range: {
      columns: ["Stage", "Count"],
      rows: [
        ["Visitors", 4200],
        ["Signups", 900],
        ["Trials", 310],
        ["Paid", 74],
      ],
    },
  },
  empty: { source: "sheet_range", range: { columns: ["Stage", "Count"], rows: [] } },
};

export const ALL_FIXTURES: WidgetFixture[] = [
  tasks,
  projects,
  calendarEntries,
  taskCounts,
  counter,
  counterGroup,
  myStats,
  sheetRange,
];

export const fixtureFor = (source: WidgetSource, widgetType?: string): WidgetData => {
  const found = ALL_FIXTURES.find((fixture) => fixture.source === source);
  if (!found) throw new Error(`no fixture for source ${source}`);
  const variant = widgetType ? found.variants?.[widgetType] : undefined;
  return variant ?? found.data;
};

/**
 * Which sources each built-in draws.
 *
 * The backend's `WIDGET_SPECS` is the authority and serves this over
 * `/dashboards/widget-catalog`; this copy exists only so the widget tests can
 * run without a backend. `registry.test.ts` is the thing that would catch a
 * type appearing on one side and not the other.
 */
export const SOURCES_BY_WIDGET: Record<string, WidgetSource[]> = {
  gantt: ["tasks", "projects", "calendar_entries"],
  kpi: ["counter", "task_counts", "my_stats", "sheet_range"],
  chart: ["task_counts", "counter_group", "sheet_range", "my_stats", "projects"],
  funnel: ["task_counts", "sheet_range"],
  progress: ["counter", "task_counts", "projects"],
  heatmap: ["my_stats", "task_counts"],
  table: ["tasks", "projects", "sheet_range", "calendar_entries"],
};
