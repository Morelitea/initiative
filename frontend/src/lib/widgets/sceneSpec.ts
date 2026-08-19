/**
 * The SceneSpec — the vocabulary every widget draws in.
 *
 * A widget is a module exposing `render(data, config) -> SceneSpec`, evaluated
 * in a QuickJS sandbox (see `runtime/`). Its output is *data describing a
 * picture*, never markup and never a DOM node: our React components map each
 * node onto trusted primitives and escape every string on the way out. That is
 * what makes running an untrusted widget safe — there is no `innerHTML` in the
 * path, no way to name a URL, and no event handler can arrive from a widget.
 *
 * The built-in widgets are written against this same vocabulary and get no
 * privileged path, so it has to be expressive enough for all seven of them
 * before any of them ships. If a built-in needs something the vocabulary can't
 * say, the vocabulary grows and every widget gains it in the same release.
 *
 * Three rules keep it safe to render:
 *
 * 1. **No free-form styling.** Colors are `Tone` names resolved to theme tokens
 *    by the renderer, so a widget can't paint itself invisible on a dark theme
 *    or imitate app chrome.
 * 2. **Text is text.** Strings are length-capped and rendered as children, so
 *    they cannot become elements.
 * 3. **Everything is bounded.** Node count, nesting depth, series points, and
 *    table cells all have caps (below). The sandbox limits what a widget may
 *    *compute*; these limit what it may *emit*, which is the part that crosses
 *    into the render tree.
 */

/** Widget API version. Bumped when the contract changes shape, independently of
 *  the dashboard definition's `schema_version`. A widget declaring a version we
 *  don't support renders a "needs a newer app version" tile. */
export const WIDGET_API_VERSION = 1;

// --- limits ----------------------------------------------------------------
//
// Sized for the widest legitimate scene each primitive produces, not for
// theoretical headroom: a year of daily heatmap cells is ~366, a Gantt over a
// large project is a few hundred bars, a table page is 100 rows.

/** Abuse backstops, not display budgets.
 *
 * Large data is normal on a dashboard — a busy initiative's table or timeline
 * legitimately runs to thousands of entries, and a widget that faithfully
 * renders its binding must never hit these. They exist so a hostile widget
 * module cannot emit an effectively unbounded scene, and they are sized an
 * order of magnitude past real content: reaching one is a malfunctioning
 * widget, which is exactly what the error tile says.
 *
 * The structural limits (nodes, depth) stay tight — they bound composition,
 * which no amount of data grows.
 */
export const SCENE_LIMITS = {
  /** Total nodes in one scene, across all nesting. Leaf collections (rows,
   *  points, cells…) are budgeted by their own caps below, not per item. */
  maxNodes: 200,
  /** `stack` nesting depth. Composition is useful; recursion is not. */
  maxDepth: 4,
  /** Rendered length of any single string (truncated, never rejected). */
  maxTextLength: 200,
  /** Series per `series` node, and points per series. */
  maxSeries: 24,
  maxPoints: 10_000,
  /** Lanes per `timeline` — counted across the whole tree, not per level, and
   *  spans per lane. */
  maxLanes: 2_000,
  maxSpansPerLane: 2_000,
  /** How deeply lanes may nest. A work breakdown is a few levels
   *  (portfolio → project → task → subtask); past that a lane label has no room
   *  left to indent into. */
  maxLaneDepth: 4,
  /** `matrix` cells (a decade of daily activity is ~3,700). */
  maxCells: 10_000,
  /** `table` shape. */
  maxColumns: 32,
  maxRows: 10_000,
  /** `funnel` stages. */
  maxStages: 32,
} as const;

// --- vocabulary ------------------------------------------------------------

/** Semantic colors. The renderer maps these to theme tokens, so widgets stay
 *  themable and can't collide with app chrome. `series-N` is the categorical
 *  palette, used when a scene needs several distinguishable colors. */
export const TONES = [
  "accent",
  "positive",
  "negative",
  "warning",
  "neutral",
  "muted",
  "series-1",
  "series-2",
  "series-3",
  "series-4",
  "series-5",
] as const;
export type Tone = (typeof TONES)[number];

/** The categorical palette, in the order the renderer cycles it when a scene
 *  gives several series no tone of their own. Five deep because the theme
 *  defines five chart colors; a sixth series wraps rather than inventing one. */
export const SERIES_TONES: readonly Tone[] = [
  "series-1",
  "series-2",
  "series-3",
  "series-4",
  "series-5",
];

/** How the renderer formats a bare number. Locale resolution is ours, not the
 *  widget's — the sandbox has no locale and no timezone. */
export const NUMBER_FORMATS = [
  "plain",
  "compact",
  "percent",
  "currency",
  "duration",
  "date",
] as const;
export type NumberFormat = (typeof NUMBER_FORMATS)[number];

export const SERIES_MARKS = ["bar", "line", "area", "pie"] as const;
export type SeriesMark = (typeof SERIES_MARKS)[number];

export const TEXT_VARIANTS = ["heading", "body", "caption"] as const;
export type TextVariant = (typeof TEXT_VARIANTS)[number];

export const STACK_DIRECTIONS = ["row", "column"] as const;
export type StackDirection = (typeof STACK_DIRECTIONS)[number];

// --- nodes -----------------------------------------------------------------

/** One big number with a label — the stat shape. `delta` is drawn as a trend
 *  chip; its sign carries the meaning, and `deltaGood` says which sign is good
 *  (falling cycle time is good, falling revenue is not). */
export interface MetricNode {
  kind: "metric";
  value: number;
  label?: string;
  format?: NumberFormat;
  /** Fraction, not percentage points: 0.12 renders as +12%. */
  delta?: number;
  deltaGood?: "up" | "down";
  caption?: string;
  tone?: Tone;
}

export interface SeriesPoint {
  /** Category label (bar/pie) or axis position (line/area). */
  x: string | number;
  y: number;
}

export interface Series {
  name?: string;
  points: SeriesPoint[];
  tone?: Tone;
}

/** Bars, lines, areas, or slices — the `chart` primitive's shape, and the one
 *  most custom widgets will reach for. */
export interface SeriesNode {
  kind: "series";
  mark: SeriesMark;
  series: Series[];
  stacked?: boolean;
  format?: NumberFormat;
  xLabel?: string;
  yLabel?: string;
  showLegend?: boolean;
}

/** How a span is drawn.
 *
 *  - `bar` — ordinary work, a block from start to end.
 *  - `summary` — a rolled-up parent, drawn as a bracket spanning what is nested
 *    under it, so a folded group still reads as "everything below me".
 *  - `milestone` — a dated instant with no duration (a due date with no start,
 *    a launch), drawn as a diamond at `start`.
 */
export const TIMELINE_SPAN_KINDS = ["bar", "summary", "milestone"] as const;
export type TimelineSpanKind = (typeof TIMELINE_SPAN_KINDS)[number];

/** What was originally planned, when the bar shows what actually happened.
 *  Drawn as a thin ghost beneath the bar so the two can be read against each
 *  other — the slip is the offset between them. */
export interface TimelineBaseline {
  start: number;
  end: number;
}

/** A time span on a lane — the Gantt bar. Times are epoch milliseconds; the
 *  renderer owns formatting them, because the sandbox has no timezone. */
export interface TimelineSpan {
  label?: string;
  start: number;
  end: number;
  tone?: Tone;
  /** 0..1, drawn as a fill inside the bar — the share of this span's work that
   *  is finished, not the share of its time that has elapsed. */
  progress?: number;
  kind?: TimelineSpanKind;
  baseline?: TimelineBaseline;
  /** A short read-out drawn beside the bar ("8/20"). Text, so a widget can say
   *  what its own denominator means rather than every renderer guessing. */
  caption?: string;
}

/** A row, and everything grouped under it.
 *
 *  Nesting is what makes a Gantt readable at more than a few dozen rows: a lane
 *  with children folds to a single summary bar, and opens to the work it stands
 *  for. Depth is capped by `maxLaneDepth`, and the total lane count by
 *  `maxLanes` across the whole tree. */
export interface TimelineLane {
  label?: string;
  spans: TimelineSpan[];
  children?: TimelineLane[];
  /** Whether the lane starts folded. Only a starting state — which lanes are
   *  open afterwards belongs to the viewer, not to the widget. */
  collapsed?: boolean;
  /** Read-out beside the label — a count, a percentage, an owner. */
  caption?: string;
  tone?: Tone;
}

export interface TimelineNode {
  kind: "timeline";
  lanes: TimelineLane[];
  /** Explicit window; omitted means "fit the spans". */
  start?: number;
  end?: number;
  /** Tick density hint. The renderer may coarsen it to fit the tile. */
  scale?: "day" | "week" | "month" | "quarter";
  /** The instant to mark with the "today" line, as the widget saw it.
   *
   *  Carried on the scene rather than read from the renderer's own clock so a
   *  preview over frozen sample rows keeps a frozen marker: the host hands the
   *  sandbox the minute it should treat as now, and this is that same minute
   *  arriving back. Omitted means "draw no marker". */
  now?: number;
}

export interface FunnelStage {
  label: string;
  value: number;
  tone?: Tone;
}

export interface FunnelNode {
  kind: "funnel";
  stages: FunnelStage[];
  format?: NumberFormat;
}

export interface ProgressNode {
  kind: "progress";
  value: number;
  min?: number;
  max?: number;
  label?: string;
  caption?: string;
  tone?: Tone;
  format?: NumberFormat;
}

/** A cell in a 2-D grid. `x`/`y` are integer grid coordinates — the widget has
 *  already decided the layout (e.g. week column, weekday row); the renderer
 *  just paints. `value` drives intensity within [0, max]. */
export interface MatrixCell {
  x: number;
  y: number;
  value: number;
  label?: string;
}

export interface MatrixNode {
  kind: "matrix";
  cells: MatrixCell[];
  /** Intensity ceiling. Omitted means "use the largest cell". */
  max?: number;
  xLabels?: string[];
  yLabels?: string[];
  tone?: Tone;
}

export interface TableColumn {
  key: string;
  label?: string;
  align?: "start" | "end";
  format?: NumberFormat;
}

/** Cells are scalars only. A cell cannot be a node, so a table can never become
 *  a nesting vector. */
export type TableCell = string | number | boolean | null;

export interface TableNode {
  kind: "table";
  columns: TableColumn[];
  rows: Record<string, TableCell>[];
}

export interface TextNode {
  kind: "text";
  text: string;
  variant?: TextVariant;
  tone?: Tone;
}

/** The "nothing to show" tile. Explicit rather than an empty scene, so a widget
 *  can say *why* it is empty. */
export interface EmptyNode {
  kind: "empty";
  message?: string;
}

/** The composition primitive — how a widget builds something we didn't
 *  anticipate (a metric above a sparkline, three stats in a row) out of parts we
 *  trust. Bounded by `maxDepth`. */
export interface StackNode {
  kind: "stack";
  direction: StackDirection;
  children: SceneNode[];
  gap?: "none" | "sm" | "md";
  /** Relative flex weights, positionally matched to `children`. */
  weights?: number[];
}

export type SceneNode =
  | MetricNode
  | SeriesNode
  | TimelineNode
  | FunnelNode
  | ProgressNode
  | MatrixNode
  | TableNode
  | TextNode
  | EmptyNode
  | StackNode;

export const SCENE_NODE_KINDS = [
  "metric",
  "series",
  "timeline",
  "funnel",
  "progress",
  "matrix",
  "table",
  "text",
  "empty",
  "stack",
] as const;
export type SceneNodeKind = (typeof SCENE_NODE_KINDS)[number];

/** What a widget module returns. */
export interface SceneSpec {
  /** Widget API version the module was written against. */
  v: number;
  scene: SceneNode;
}
