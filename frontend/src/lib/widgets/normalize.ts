/**
 * API payloads → the widget data envelope.
 *
 * Pure functions, deliberately separate from the hooks that fetch: they are the
 * whole contract between our endpoints and every widget, so they are worth
 * testing without a query client. `dataShapes.ts` documents the shapes; this
 * produces them.
 *
 * The normalization is not cosmetic. It means a widget written against
 * `task_counts` keeps working when the task serializer changes, and it converts
 * every timestamp to epoch milliseconds — the sandbox has a frozen clock and no
 * timezone, so a widget must never be handed a date string to parse.
 */

import type {
  CalendarEventSummary,
  CounterGroupRead,
  CounterRead,
  DocumentRead,
  ProjectRead,
  TaskListRead,
} from "@/api/generated/initiativeAPI.schemas";
import { keyOf, parseA1Range } from "@/lib/spreadsheet/coords";

import type {
  CalendarEntryRow,
  CounterValue,
  CountRow,
  ProjectRow,
  SheetRange,
  TaskRow,
  WidgetData,
} from "./dataShapes";

/** ISO string → epoch ms, or null. A widget only ever sees numbers. */
export const toEpoch = (value: string | null | undefined): number | null => {
  if (!value) return null;
  const parsed = Date.parse(value);
  return Number.isNaN(parsed) ? null : parsed;
};

/** Counter values arrive as decimal strings (they are NUMERIC server-side). */
const toNumber = (value: string | number | null | undefined): number | null => {
  if (value === null || value === undefined) return null;
  const parsed = typeof value === "number" ? value : Number(value);
  return Number.isFinite(parsed) ? parsed : null;
};

const UTC_DAY = 86_400_000;

/** Midnight UTC for a timestamp — the bucket key for day-grouped counts. */
export const startOfUtcDay = (epoch: number): number => Math.floor(epoch / UTC_DAY) * UTC_DAY;

// --- per-source normalizers -------------------------------------------------

export const normalizeTasks = (tasks: TaskListRead[]): TaskRow[] =>
  tasks.map((task) => ({
    id: task.id,
    title: task.title,
    status: task.task_status?.name ?? "",
    statusCategory: task.task_status?.category ?? "todo",
    priority: task.priority ?? null,
    startDate: toEpoch(task.start_date),
    dueDate: toEpoch(task.due_date),
    completedAt: toEpoch(task.completed_at),
    projectId: task.project_id ?? null,
    projectName: task.project_name ?? null,
    assignees: (task.assignees ?? []).map((assignee) => assignee.full_name ?? "").filter(Boolean),
  }));

export const normalizeProjects = (
  projects: ProjectRead[],
  /** Task counts per project, when a task query is in play. Absent means the
   *  progress columns read as zero rather than as a guess. */
  taskCounts?: Map<number, { total: number; done: number }>
): ProjectRow[] =>
  projects.map((project) => {
    const counts = taskCounts?.get(project.id) ?? { total: 0, done: 0 };
    return {
      id: project.id,
      name: project.name,
      startDate: toEpoch(project.start_date),
      endDate: toEpoch(project.end_date),
      progress: counts.total > 0 ? counts.done / counts.total : 0,
      taskCount: counts.total,
      doneCount: counts.done,
    };
  });

/** Calendar *events* only. The entries endpoint also returns task markers, but
 *  those are the `tasks` source's business — a widget bound to
 *  `calendar_entries` asked for what is on the calendar, not for work items
 *  duplicated from another binding. */
export const normalizeCalendarEntries = (
  events: CalendarEventSummary[],
  calendarNames?: Map<number, string>
): CalendarEntryRow[] =>
  events.flatMap((event) => {
    const start = toEpoch(event.start_at);
    if (start === null) return [];
    return [
      {
        id: event.id,
        title: event.title,
        start,
        // An event with no usable end is an instant; give it a visible width
        // rather than a zero-length span the renderer would collapse.
        end: toEpoch(event.end_at) ?? start + 3_600_000,
        calendarName: calendarNames?.get(event.calendar_id) ?? null,
        allDay: Boolean(event.all_day),
      },
    ];
  });

export const normalizeCounter = (counter: CounterRead): CounterValue => ({
  name: counter.name,
  value: toNumber(counter.count) ?? 0,
  min: toNumber(counter.min),
  max: toNumber(counter.max),
  unit: null,
});

export const normalizeCounterGroup = (
  group: CounterGroupRead
): { name: string; counters: CounterValue[] } => ({
  name: group.name,
  counters: (group.counters ?? []).map(normalizeCounter),
});

// --- derived counts ---------------------------------------------------------

/** How a `task_counts` binding groups. Day-grouping is the only one with a
 *  calendar shape, which is what a heatmap needs. */
export type CountBucket =
  | "status_category"
  | "status"
  | "priority"
  | "project"
  | "assignee"
  | "day";

const DEFAULT_BUCKET: CountBucket = "status_category";

/**
 * Counts derived from the task rows already fetched, rather than from a second
 * endpoint. Two widgets on one canvas bound to the same tasks therefore share a
 * single query and disagree about nothing.
 */
export const countTasks = (tasks: TaskRow[], bucket: CountBucket = DEFAULT_BUCKET): CountRow[] => {
  if (bucket === "day") {
    // Completion is the only per-day event a task carries; an incomplete task
    // has no day to sit on, so it is absent rather than placed arbitrarily.
    const byDay = new Map<number, number>();
    for (const task of tasks) {
      if (task.completedAt === null) continue;
      const day = startOfUtcDay(task.completedAt);
      byDay.set(day, (byDay.get(day) ?? 0) + 1);
    }
    return [...byDay.entries()]
      .sort(([a], [b]) => a - b)
      .map(([date, count]) => ({
        bucket: new Date(date).toISOString().slice(0, 10),
        count,
        date,
      }));
  }

  const keyFor = (task: TaskRow): string[] => {
    switch (bucket) {
      case "status":
        return [task.status || "—"];
      case "priority":
        return [task.priority ?? "none"];
      case "project":
        return [task.projectName ?? "Unassigned"];
      case "assignee":
        return task.assignees.length ? task.assignees : ["Unassigned"];
      default:
        return [task.statusCategory];
    }
  };

  const counts = new Map<string, number>();
  for (const task of tasks) {
    for (const key of keyFor(task)) {
      counts.set(key, (counts.get(key) ?? 0) + 1);
    }
  }
  return [...counts.entries()].map(([label, count]) => ({ bucket: label, count }));
};

/** Per-project totals, for the project rows' progress columns. */
export const countTasksByProject = (
  tasks: TaskRow[]
): Map<number, { total: number; done: number }> => {
  const counts = new Map<number, { total: number; done: number }>();
  for (const task of tasks) {
    if (task.projectId === null) continue;
    const entry = counts.get(task.projectId) ?? { total: 0, done: 0 };
    entry.total += 1;
    if (task.statusCategory === "done") entry.done += 1;
    counts.set(task.projectId, entry);
  }
  return counts;
};

// --- spreadsheet ranges -----------------------------------------------------

interface SheetLike {
  id?: string;
  name?: string;
  cells?: Record<string, unknown>;
}

/**
 * Pull an A1 range out of a spreadsheet document.
 *
 * Reuses the spreadsheet module's own parser and cell keying rather than
 * re-deriving them, so a range means here exactly what it means in the editor.
 * The first row becomes column headers when it is all text — the usual shape of
 * a range someone points a chart at.
 */
export const normalizeSheetRange = (
  document: DocumentRead,
  sheetName: string | null | undefined,
  range: string | null | undefined
): SheetRange | null => {
  const content = document.content as { sheets?: SheetLike[] } | null;
  const sheets = content?.sheets ?? [];
  if (!sheets.length) return null;

  const sheet = sheetName
    ? sheets.find((s) => s.name === sheetName || s.id === sheetName)
    : sheets[0];
  if (!sheet?.cells) return null;

  const box = range ? parseA1Range(range) : null;
  if (!box) return null;

  const rows: (string | number | boolean | null)[][] = [];
  for (let row = box.r1; row <= box.r2; row++) {
    const line: (string | number | boolean | null)[] = [];
    for (let col = box.c1; col <= box.c2; col++) {
      const value = sheet.cells[keyOf(row, col)];
      line.push(
        typeof value === "string" || typeof value === "number" || typeof value === "boolean"
          ? value
          : null
      );
    }
    rows.push(line);
  }
  if (!rows.length) return { columns: [], rows: [] };

  const [firstRow] = rows;
  const headerLooksLikeLabels =
    rows.length > 1 && firstRow.every((cell) => typeof cell === "string" && cell !== "");

  return headerLooksLikeLabels
    ? { columns: firstRow.map(String), rows: rows.slice(1) }
    : { columns: firstRow.map((_, index) => `Column ${index + 1}`), rows };
};

/** The envelope for a source we fetched nothing for — a binding whose ids the
 *  instance config has not filled in yet. */
export const emptyDataFor = (source: WidgetData["source"]): WidgetData => {
  switch (source) {
    case "counter":
      return {
        source: "counter",
        counter: { name: "", value: 0, min: null, max: null, unit: null },
      };
    case "counter_group":
      return { source: "counter_group", name: "", counters: [] };
    case "sheet_range":
      return { source: "sheet_range", range: { columns: [], rows: [] } };
    case "projects":
      return { source: "projects", rows: [], tasks: [] };
    default:
      return { source, rows: [] } as WidgetData;
  }
};
