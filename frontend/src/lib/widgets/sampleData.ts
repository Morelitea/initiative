/**
 * Sample data in the shapes `dataShapes.ts` documents.
 *
 * Ships with the app rather than living beside the tests, because the widget
 * picker previews every widget by *running* it — the same sandbox, validator,
 * and renderer a live tile uses, over these rows. So someone choosing a widget
 * sees the real thing before adding it, and the widget tests exercise the same
 * contract the previews do. Frozen values throughout: the sandbox has a frozen
 * clock, so a preview renders identically every time.
 */

import type { WidgetData, WidgetSource } from "./dataShapes";
import { emptyDataFor } from "./normalize";

const DAY = 86_400_000;
/** A fixed anchor — the widgets get a frozen clock, so samples get a frozen
 *  calendar. Renders stay byte-identical across runs. */
const T0 = Date.UTC(2026, 7, 3);

/** The clock a preview runs under. Previews draw these frozen samples, so a
 *  clock-reading widget (the agenda) must see a frozen "now" that sits inside
 *  them — the real clock would drift past the samples and empty the preview a
 *  little more each day. Live tiles never use this; the host hands them the
 *  real minute. */
export const SAMPLE_NOW = T0;

export interface WidgetSample {
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

const tasks: WidgetSample = {
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
  variants: {
    // A week of due dates straddling the sample clock, so the preview shows
    // the widget's whole point: late work flagged above the queue of what is
    // coming. One finished task and one undated task prove both stay out.
    agenda: {
      source: "tasks",
      rows: [
        { title: "Chase the vendor", due: -4, status: "Blocked", category: "todo" },
        { title: "Sign the venue", due: -1, status: "In progress", category: "in_progress" },
        { title: "Draft the spec", due: 1, status: "In review", category: "in_progress" },
        { title: "Order supplies", due: 2, status: "To do", category: "todo" },
        { title: "Book travel", due: 3, status: "To do", category: "todo" },
        { title: "Publish the plan", due: 6, status: "In progress", category: "in_progress" },
        { title: "Send invitations", due: 9, status: "To do", category: "todo" },
        { title: "Ship the migration", due: 1, status: "Done", category: "done" },
        { title: "Tidy the backlog", due: null, status: "To do", category: "todo" },
      ].map((task, index) => ({
        id: 400 + index,
        title: task.title,
        status: task.status,
        statusCategory: task.category,
        priority: (["high", "medium", "low", null] as const)[index % 4],
        startDate: task.due === null ? null : T0 + (task.due - 5) * DAY,
        dueDate: task.due === null ? null : T0 + task.due * DAY,
        completedAt: task.category === "done" ? T0 - DAY : null,
        projectId: index % 2 === 0 ? 10 : 11,
        projectName: index % 2 === 0 ? "Apollo" : "Borealis",
        assignees: [index % 2 === 0 ? "Ada" : "Grace"],
      })),
    },
  },
};

const projects: WidgetSample = {
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

const calendarEntries: WidgetSample = {
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
  variants: {
    // A fuller fortnight than the base pair, anchored around the sample clock:
    // one event already over (the agenda must drop it), one under way, and a
    // run of upcoming ones for the list itself.
    agenda: {
      source: "calendar_entries",
      rows: [
        { title: "Sprint planning", offset: -2, hours: 1 },
        { title: "All-hands", offset: 0, hours: 26 },
        { title: "Design review", offset: 9, hours: 1 },
        { title: "Vendor call", offset: 10, hours: 2 },
        { title: "Release cut", offset: 12, hours: 1 },
        { title: "Retro", offset: 14, hours: 1 },
        { title: "Roadmap workshop", offset: 16, hours: 3 },
      ].map((event, index) => ({
        id: 110 + index,
        title: event.title,
        start: T0 + event.offset * DAY - 2 * 3_600_000,
        end: T0 + event.offset * DAY + (event.hours - 2) * 3_600_000,
        calendarName: index % 2 === 0 ? "Team" : "Releases",
        allDay: event.hours >= 24,
      })),
    },
  },
};

const taskCounts: WidgetSample = {
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
    // shape, and the one a heatmap binding would ask for. Half a year of days,
    // so the preview fills a contribution grid the way real activity does:
    // a weekly rhythm, quiet weekends, and the occasional busy spell — all
    // deterministic, so the picker draws the same picture every time.
    heatmap: {
      source: "task_counts",
      // Starting on a Sunday keeps the 26-week grid a clean rectangle — a
      // mid-week start would leave the first column ragged.
      rows: Array.from({ length: 182 }, (_, index) => {
        const windowStart = T0 - 181 * DAY;
        const sunday = windowStart - new Date(windowStart).getUTCDay() * DAY;
        const date = sunday + index * DAY;
        const weekday = new Date(date).getUTCDay();
        const weekend = weekday === 0 || weekday === 6;
        const rhythm = (index * 7) % 5;
        const spike = index % 23 === 0 ? 4 : 0;
        const count = weekend ? (index % 13 === 0 ? 2 : 0) : rhythm + spike;
        return {
          bucket: new Date(date).toISOString().slice(0, 10),
          count,
          date,
        };
      }),
    },
  },
};

const counter: WidgetSample = {
  source: "counter",
  data: {
    source: "counter",
    counter: { name: "Beds made", value: 34, min: 0, max: 50, unit: "beds" },
  },
  // A counter with no ceiling is the interesting empty-ish case: progress has
  // no denominator to draw, while the stat widget is perfectly happy.
  empty: {
    source: "counter",
    counter: { name: "Signups", value: 0, min: null, max: null, unit: null },
  },
};

const counterGroup: WidgetSample = {
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

const sheetRange: WidgetSample = {
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

export const ALL_SAMPLES: WidgetSample[] = [
  tasks,
  projects,
  calendarEntries,
  taskCounts,
  counter,
  counterGroup,
  sheetRange,
];

/**
 * Sample rows for a source, in the shape a given widget wants them.
 *
 * Total on purpose: the picker previews whatever the *served* catalog offers, so
 * a source this build has no sample for previews as an empty tile rather than
 * taking the dialog down with it. `sampleData.test.ts` is what stops that from
 * becoming a silent gap.
 */
export const sampleFor = (source: WidgetSource, widgetType?: string): WidgetData => {
  const found = ALL_SAMPLES.find((sample) => sample.source === source);
  const variant = widgetType ? found?.variants?.[widgetType] : undefined;
  return variant ?? found?.data ?? emptyDataFor(source);
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
  agenda: ["calendar_entries", "tasks"],
  stat: ["counter", "task_counts", "sheet_range"],
  chart: ["task_counts", "counter_group", "sheet_range", "projects"],
  funnel: ["task_counts", "sheet_range"],
  progress: ["counter", "task_counts", "projects"],
  heatmap: ["task_counts"],
  table: ["tasks", "projects", "sheet_range", "calendar_entries"],
};
