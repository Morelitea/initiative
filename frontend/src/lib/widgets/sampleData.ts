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

import type { TaskRow, WidgetData, WidgetSource } from "./dataShapes";
import { emptyDataFor } from "./normalize";

const DAY = 86_400_000;
/** A fixed anchor — the widgets get a frozen clock, so samples get a frozen
 *  calendar. Renders stay byte-identical across runs. */
const T0 = Date.UTC(2026, 7, 3);

/** The clock a preview runs under. Previews draw these frozen samples, so a
 *  clock-reading widget (the gantt marking work late) must see a frozen "now"
 *  that sits inside them — the real clock would drift past the samples and
 *  shift how they read a little more each day. Live tiles never use this; the
 *  host hands them the real minute. */
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

/**
 * Enough tasks to show the shapes a Gantt has to draw: work across more than
 * one project, work with only a due date (a milestone), work finished late
 * (a bar that overran its baseline), and work already overdue. A sparser set
 * would preview as a tidy ladder and hide every one of them.
 */
const tasks: WidgetSample = {
  source: "tasks",
  data: {
    source: "tasks",
    rows: [
      {
        id: 1,
        title: "Draft the spec",
        status: "Done",
        statusCategory: "done",
        priority: "high",
        startDate: T0 - 18 * DAY,
        dueDate: T0 - 10 * DAY,
        completedAt: T0 - 12 * DAY,
        projectId: 10,
        projectName: "Apollo",
        assignees: ["Ada"],
        createdAt: T0 - 24 * DAY,
        updatedAt: T0 - 0 * DAY,
        tags: ["backend"],
        subtaskDone: 3,
        subtaskTotal: 3,
        commentCount: 4,
      },
      {
        id: 2,
        title: "Ship the migration",
        status: "Done",
        statusCategory: "done",
        priority: "medium",
        startDate: T0 - 9 * DAY,
        dueDate: T0 - 3 * DAY,
        // Finished four days past the date it was planned for — the case the
        // baseline ghost exists to make visible.
        completedAt: T0 + DAY,
        projectId: 10,
        projectName: "Apollo",
        assignees: ["Grace", "Ada"],
        createdAt: T0 - 22 * DAY,
        updatedAt: T0 - 1 * DAY,
        tags: ["backend", "migration"],
        subtaskDone: 5,
        subtaskTotal: 5,
        commentCount: 2,
      },
      {
        id: 3,
        title: "Migrate the search index",
        status: "In progress",
        statusCategory: "in_progress",
        priority: "high",
        startDate: T0 - 2 * DAY,
        dueDate: T0 + 9 * DAY,
        completedAt: null,
        projectId: 10,
        projectName: "Apollo",
        assignees: ["Grace"],
        createdAt: T0 - 20 * DAY,
        updatedAt: T0 - 2 * DAY,
        tags: ["design"],
        subtaskDone: 1,
        subtaskTotal: 4,
        commentCount: 0,
      },
      {
        id: 4,
        title: "Beta sign-off",
        status: "To do",
        statusCategory: "todo",
        priority: "high",
        // A due date and nothing else: a dated instant, drawn as a diamond.
        startDate: null,
        dueDate: T0 + 14 * DAY,
        completedAt: null,
        projectId: 10,
        projectName: "Apollo",
        assignees: ["Ada"],
        createdAt: T0 - 18 * DAY,
        updatedAt: T0 - 3 * DAY,
        tags: [],
        subtaskDone: 0,
        subtaskTotal: 0,
        commentCount: 1,
      },
      {
        id: 5,
        title: "Rewrite the onboarding copy",
        status: "In progress",
        statusCategory: "in_progress",
        priority: "medium",
        startDate: T0 - 4 * DAY,
        dueDate: T0 + 20 * DAY,
        completedAt: null,
        projectId: 11,
        projectName: "Borealis",
        assignees: ["Lin"],
        createdAt: T0 - 16 * DAY,
        updatedAt: T0 - 4 * DAY,
        tags: ["api"],
        subtaskDone: 2,
        subtaskTotal: 6,
        commentCount: 7,
      },
      {
        id: 6,
        title: "Localize the emails",
        status: "To do",
        statusCategory: "todo",
        priority: "low",
        startDate: T0 + 6 * DAY,
        dueDate: T0 + 24 * DAY,
        completedAt: null,
        projectId: 11,
        projectName: "Borealis",
        assignees: ["Lin", "Ada"],
        createdAt: T0 - 14 * DAY,
        updatedAt: T0 - 0 * DAY,
        tags: ["docs"],
        subtaskDone: 0,
        subtaskTotal: 3,
        commentCount: 0,
      },
      {
        id: 7,
        title: "Audit the tracking plan",
        status: "Done",
        statusCategory: "done",
        priority: "low",
        startDate: T0 - 6 * DAY,
        dueDate: T0 + 2 * DAY,
        completedAt: T0 - DAY,
        projectId: 11,
        projectName: "Borealis",
        assignees: ["Grace"],
        createdAt: T0 - 12 * DAY,
        updatedAt: T0 - 1 * DAY,
        tags: ["infra"],
        subtaskDone: 4,
        subtaskTotal: 4,
        commentCount: 3,
      },
      {
        id: 8,
        title: "Chase the vendor",
        status: "Blocked",
        statusCategory: "todo",
        priority: null,
        // Past its date and still open — the overdue tone.
        startDate: T0 - 8 * DAY,
        dueDate: T0 - 2 * DAY,
        completedAt: null,
        projectId: null,
        projectName: null,
        assignees: [],
        createdAt: T0 - 10 * DAY,
        updatedAt: T0 - 2 * DAY,
        tags: [],
        subtaskDone: 0,
        subtaskTotal: 0,
        commentCount: 0,
      },
      {
        id: 9,
        title: "Book the launch venue",
        status: "To do",
        statusCategory: "todo",
        priority: "medium",
        startDate: T0 + 11 * DAY,
        dueDate: T0 + 13 * DAY,
        completedAt: null,
        projectId: null,
        projectName: null,
        assignees: ["Lin"],
        createdAt: T0 - 8 * DAY,
        updatedAt: T0 - 3 * DAY,
        tags: ["research"],
        subtaskDone: 1,
        subtaskTotal: 2,
        commentCount: 2,
      },
    ],
  },
  empty: { source: "tasks", rows: [] },
};

const projectRows = [
  {
    id: 10,
    name: "Apollo",
    startDate: T0 - 20 * DAY,
    endDate: T0 + 16 * DAY,
    progress: 0.5,
    taskCount: 4,
    doneCount: 2,
    ownerName: "Ada",
    tags: ["platform"],
  },
  {
    id: 11,
    name: "Borealis",
    startDate: T0 - 6 * DAY,
    endDate: T0 + 26 * DAY,
    progress: 1 / 3,
    taskCount: 3,
    doneCount: 1,
    ownerName: "Grace",
    tags: ["growth"],
  },
  {
    id: 12,
    name: "Cygnus",
    startDate: T0 - 30 * DAY,
    endDate: T0 - 4 * DAY,
    progress: 1,
    taskCount: 5,
    doneCount: 5,
    ownerName: "Linus",
    tags: [],
  },
];

/** The same rows the tasks sample carries — a project's own work is what it
 *  folds open to, so the two samples have to agree on `projectId`. */
const projects: WidgetSample = {
  source: "projects",
  data: {
    source: "projects",
    rows: projectRows,
    tasks: (tasks.data as { rows: TaskRow[] }).rows,
  },
  empty: { source: "projects", rows: [], tasks: [] },
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
        location: "Room 2",
        attendees: ["Ada", "Grace"],
        tags: ["ceremony"],
      },
      {
        id: 101,
        title: "Retro",
        start: T0 + 8 * DAY,
        end: T0 + 8 * DAY + 3_600_000,
        calendarName: "Team",
        allDay: false,
        location: null,
        attendees: ["Ada"],
        tags: [],
      },
    ],
  },
  empty: { source: "calendar_entries", rows: [] },
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
  stat: ["counter", "task_counts", "sheet_range"],
  chart: ["task_counts", "counter_group", "sheet_range", "projects"],
  funnel: ["task_counts", "sheet_range"],
  progress: ["counter", "task_counts", "projects"],
  heatmap: ["task_counts"],
  table: ["tasks", "projects", "sheet_range", "calendar_entries"],
};
