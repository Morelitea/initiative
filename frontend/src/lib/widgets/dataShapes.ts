/**
 * What a widget receives.
 *
 * A binding names a `source` (§6 of the design); the host resolves it through
 * the ordinary RLS-gated hooks — per viewer, through the six gates — and hands
 * the widget the normalized envelope below. The widget never names an endpoint
 * and never sees a token: by the time it runs, authorization has already
 * happened and it is looking at rows the viewer could have loaded themselves.
 *
 * Normalizing here rather than passing API payloads through has two payoffs:
 * a widget written against `task_counts` keeps working when the endpoint's
 * serializer changes, and every widget — ours or a listing's — reads the same
 * documented shape.
 *
 * **All timestamps are epoch milliseconds, UTC.** The sandbox has a frozen
 * clock and no timezone, deliberately: rendering a timestamp for a human is the
 * renderer's job, not the widget's.
 *
 * The fetchers that produce these land with the canvas (Phase 2b). This module
 * is the contract they will satisfy, and what `fixtures.ts` mirrors so the
 * widgets are testable now.
 */

export interface TaskRow {
  id: number;
  title: string;
  status: string;
  /** Coarse bucket shared by all projects: `todo` | `in_progress` | `done` | … */
  statusCategory: string;
  priority: string | null;
  startDate: number | null;
  dueDate: number | null;
  completedAt: number | null;
  projectId: number | null;
  projectName: string | null;
  assignees: string[];
}

export interface ProjectRow {
  id: number;
  name: string;
  startDate: number | null;
  endDate: number | null;
  /** 0..1 across the project's tasks. */
  progress: number;
  taskCount: number;
  doneCount: number;
}

/**
 * The `projects` envelope.
 *
 * `tasks` is the same shape the `tasks` source hands over, and it is here
 * because the host already has it: the progress columns above are counted from
 * those very rows, so a widget that draws a project as a foldable group of its
 * work needs no second binding and no second request. Rows carry `projectId`,
 * which is what joins the two halves.
 */
export interface ProjectsData {
  source: "projects";
  rows: ProjectRow[];
  tasks: TaskRow[];
}

export interface CalendarEntryRow {
  id: number;
  title: string;
  start: number;
  end: number;
  calendarName: string | null;
  allDay: boolean;
}

/** A pre-aggregated count, whatever the binding grouped by (status category,
 *  assignee, project, priority, day). */
export interface CountRow {
  bucket: string;
  count: number;
  /** Present when the bucket is a calendar day, for date-shaped renderings. */
  date?: number;
}

export interface CounterValue {
  name: string;
  value: number;
  min: number | null;
  max: number | null;
  unit: string | null;
}

export interface SheetRange {
  columns: string[];
  rows: (string | number | boolean | null)[][];
}

/**
 * Rows from an installed app's data source.
 *
 * The one source whose row shape this build does not describe, and deliberately
 * so. An app's rows are the app's — the proxy passes them through without
 * reading inside them, and the widget that draws them ships in the same
 * manifest, so the two agree without anything here mediating.
 *
 * They are still *data*. The sandbox receives values, and the SceneSpec it has
 * to return has no `html` mark, no raw-string passthrough and no way to name a
 * URL, so an app cannot turn its own rows into rendering.
 */
export interface AppRows {
  source: "app";
  rows: unknown[];
}

export type WidgetData =
  | { source: "tasks"; rows: TaskRow[] }
  | ProjectsData
  | { source: "calendar_entries"; rows: CalendarEntryRow[] }
  | { source: "task_counts"; rows: CountRow[] }
  | { source: "counter"; counter: CounterValue }
  | { source: "counter_group"; name: string; counters: CounterValue[] }
  | { source: "sheet_range"; range: SheetRange }
  | AppRows;

export type WidgetSource = WidgetData["source"];

/** Widget-level display options, already validated by the backend against the
 *  primitive's allow-list (`WIDGET_SPECS[...].options`). Values are strings —
 *  the option vocabulary is a flat set of literals on both sides. */
export type WidgetConfig = Record<string, string>;
