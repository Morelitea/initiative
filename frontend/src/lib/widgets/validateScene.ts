/**
 * The trust boundary for widget output.
 *
 * Everything a widget returns crosses this function before any component sees
 * it, whether the widget is one of ours or a listing's. It never trusts the
 * shape it is given: it *rebuilds* the scene from validated parts, so unknown
 * keys, inherited properties, and anything hiding on the prototype are dropped
 * by construction rather than by inspection.
 *
 * The split between failing and dropping mirrors the backend's definition
 * normalizer: a value that is present but wrong is an error the widget author
 * should see, while a key we don't recognize is simply not copied across.
 * Strings are truncated rather than rejected — an over-long label is a display
 * problem, not a malformed scene.
 */

import {
  type MatrixCell,
  NUMBER_FORMATS,
  type NumberFormat,
  SCENE_LIMITS,
  type SceneNode,
  type SceneSpec,
  SERIES_LABELS,
  SERIES_MARKS,
  type Series,
  type SeriesPoint,
  STACK_DIRECTIONS,
  type TableCell,
  type TableColumn,
  TEXT_VARIANTS,
  TIMELINE_SPAN_KINDS,
  type TimelineBaseline,
  type TimelineLane,
  type TimelineSpan,
  TONES,
  type Tone,
  WIDGET_API_VERSION,
} from "./sceneSpec";

/** Stable machine codes. The error tile maps these through `widgets.json`. */
export const SceneErrorCode = {
  NOT_AN_OBJECT: "SCENE_NOT_AN_OBJECT",
  API_VERSION_UNSUPPORTED: "SCENE_API_VERSION_UNSUPPORTED",
  NODE_KIND_UNKNOWN: "SCENE_NODE_KIND_UNKNOWN",
  NODE_INVALID: "SCENE_NODE_INVALID",
  VALUE_NOT_FINITE: "SCENE_VALUE_NOT_FINITE",
  ENUM_INVALID: "SCENE_ENUM_INVALID",
  TOO_MANY_NODES: "SCENE_TOO_MANY_NODES",
  TOO_DEEP: "SCENE_TOO_DEEP",
  TOO_LARGE: "SCENE_TOO_LARGE",
} as const;
export type SceneErrorCode = (typeof SceneErrorCode)[keyof typeof SceneErrorCode];

export type SceneValidation = { ok: true; spec: SceneSpec } | { ok: false; code: SceneErrorCode };

class SceneError extends Error {
  constructor(readonly code: SceneErrorCode) {
    super(code);
  }
}

// Annotated on the binding, not just the arrow: TypeScript only treats a call
// as never-returning (and so narrows the code after it) when the called entity
// carries an explicit type annotation.
const fail: (code: SceneErrorCode) => never = (code) => {
  throw new SceneError(code);
};

// --- scalars ---------------------------------------------------------------

const isPlainObject = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);

/** Rejects NaN and ±Infinity: they survive JSON round-trips as `null` in some
 *  encoders and break every downstream scale computation in the others. */
const num = (value: unknown): number => {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    fail(SceneErrorCode.VALUE_NOT_FINITE);
  }
  return value as number;
};

const optNum = (value: unknown): number | undefined =>
  value === undefined || value === null ? undefined : num(value);

const text = (value: unknown): string => {
  if (typeof value !== "string") fail(SceneErrorCode.NODE_INVALID);
  return (value as string).slice(0, SCENE_LIMITS.maxTextLength);
};

const optText = (value: unknown): string | undefined =>
  value === undefined || value === null ? undefined : text(value);

const optBool = (value: unknown): boolean | undefined =>
  value === undefined || value === null ? undefined : Boolean(value);

/** Membership in a closed set. Unknown members fail loudly rather than being
 *  dropped, because a widget asking for a tone we don't have is a bug worth
 *  surfacing to its author. */
const oneOf = <T extends string>(value: unknown, allowed: readonly T[]): T | undefined => {
  if (value === undefined || value === null) return undefined;
  if (typeof value !== "string" || !allowed.includes(value as T)) {
    fail(SceneErrorCode.ENUM_INVALID);
  }
  return value as T;
};

const optTone = (value: unknown): Tone | undefined => oneOf(value, TONES);
const optFormat = (value: unknown): NumberFormat | undefined => oneOf(value, NUMBER_FORMATS);

const asList = (value: unknown): unknown[] => {
  if (!Array.isArray(value)) fail(SceneErrorCode.NODE_INVALID);
  return value as unknown[];
};

/** For leaf collections, whose cap is domain-specific (points, rows, cells).
 *  Nested children are bounded by the node budget instead, so that overflow
 *  reports as `TOO_MANY_NODES` rather than as an arbitrary array limit. */
const arrayOf = (value: unknown, cap: number): unknown[] => {
  const list = asList(value);
  if (list.length > cap) fail(SceneErrorCode.TOO_LARGE);
  return list;
};

/** Copies only the keys we name, so `undefined` optionals don't become explicit
 *  `undefined` properties in the rebuilt node. */
const compact = <T extends Record<string, unknown>>(node: T): T => {
  const out = {} as Record<string, unknown>;
  for (const [key, value] of Object.entries(node)) {
    if (value !== undefined) out[key] = value;
  }
  return out as T;
};

// --- node parts ------------------------------------------------------------

const parsePoint = (raw: unknown): SeriesPoint => {
  if (!isPlainObject(raw)) fail(SceneErrorCode.NODE_INVALID);
  const point = raw as Record<string, unknown>;
  const x = point.x;
  if (typeof x !== "string" && typeof x !== "number") {
    fail(SceneErrorCode.NODE_INVALID);
  }
  return {
    x: typeof x === "string" ? text(x) : num(x),
    y: num(point.y),
  };
};

const parseSeries = (raw: unknown): Series => {
  if (!isPlainObject(raw)) fail(SceneErrorCode.NODE_INVALID);
  return compact({
    name: optText(raw.name),
    points: arrayOf(raw.points, SCENE_LIMITS.maxPoints).map(parsePoint),
    tone: optTone(raw.tone),
  });
};

const parseBaseline = (raw: unknown): TimelineBaseline | undefined => {
  if (raw === undefined || raw === null) return undefined;
  if (!isPlainObject(raw)) fail(SceneErrorCode.NODE_INVALID);
  return { start: num(raw.start), end: num(raw.end) };
};

const parseSpan = (raw: unknown): TimelineSpan => {
  if (!isPlainObject(raw)) fail(SceneErrorCode.NODE_INVALID);
  return compact({
    label: optText(raw.label),
    start: num(raw.start),
    end: num(raw.end),
    tone: optTone(raw.tone),
    progress: optNum(raw.progress),
    kind: oneOf(raw.kind, TIMELINE_SPAN_KINDS),
    baseline: parseBaseline(raw.baseline),
    caption: optText(raw.caption),
  });
};

/**
 * A lane and everything nested under it.
 *
 * Lanes are counted against one budget shared by the whole tree rather than a
 * cap per level: a chain of 2,000 single-child lanes is exactly as much drawing
 * as a flat 2,000, so only the total is worth bounding. Depth is capped
 * separately because it bounds *structure*, which no amount of data grows —
 * the same split the node budget makes.
 */
const parseLane = (raw: unknown, depth: number, budget: LaneBudget): TimelineLane => {
  if (depth > SCENE_LIMITS.maxLaneDepth) fail(SceneErrorCode.TOO_DEEP);
  if (++budget.lanes > SCENE_LIMITS.maxLanes) fail(SceneErrorCode.TOO_LARGE);
  if (!isPlainObject(raw)) fail(SceneErrorCode.NODE_INVALID);
  return compact({
    label: optText(raw.label),
    spans: arrayOf(raw.spans, SCENE_LIMITS.maxSpansPerLane).map(parseSpan),
    children:
      raw.children === undefined || raw.children === null
        ? undefined
        : asList(raw.children).map((child) => parseLane(child, depth + 1, budget)),
    collapsed: optBool(raw.collapsed),
    caption: optText(raw.caption),
    tone: optTone(raw.tone),
  });
};

const parseCell = (raw: unknown): MatrixCell => {
  if (!isPlainObject(raw)) fail(SceneErrorCode.NODE_INVALID);
  return compact({
    x: num(raw.x),
    y: num(raw.y),
    value: num(raw.value),
    label: optText(raw.label),
  });
};

const parseColumn = (raw: unknown): TableColumn => {
  if (!isPlainObject(raw)) fail(SceneErrorCode.NODE_INVALID);
  return compact({
    key: text(raw.key),
    label: optText(raw.label),
    align: oneOf(raw.align, ["start", "end"] as const),
    format: optFormat(raw.format),
  });
};

/** Table cells are scalars, or a scalar with a tone. Anything else — including
 *  an object that looks like a node — is dropped to `null`, so a table can
 *  never nest: the toned form is rebuilt from exactly two fields, and its
 *  `value` goes through this same function, which has no object branch of its
 *  own to recurse into. */
const parseScalarCell = (value: unknown): string | number | boolean | null => {
  if (value === null || value === undefined) return null;
  if (typeof value === "string") return text(value);
  if (typeof value === "number") return num(value);
  if (typeof value === "boolean") return value;
  return null;
};

const parseTableCell = (value: unknown): TableCell => {
  if (isPlainObject(value) && "value" in (value as Record<string, unknown>)) {
    const cell = value as Record<string, unknown>;
    return compact({ value: parseScalarCell(cell.value), tone: optTone(cell.tone) });
  }
  return parseScalarCell(value);
};

const parseRow = (raw: unknown, columns: TableColumn[]): Record<string, TableCell> => {
  if (!isPlainObject(raw)) fail(SceneErrorCode.NODE_INVALID);
  const row: Record<string, TableCell> = {};
  // Driven by the declared columns, so a row cannot introduce keys the header
  // never announced.
  for (const column of columns) {
    row[column.key] = parseTableCell((raw as Record<string, unknown>)[column.key]);
  }
  return row;
};

// --- nodes -----------------------------------------------------------------

interface Budget {
  nodes: number;
}

interface LaneBudget {
  lanes: number;
}

const parseNode = (raw: unknown, depth: number, budget: Budget): SceneNode => {
  if (depth > SCENE_LIMITS.maxDepth) fail(SceneErrorCode.TOO_DEEP);
  if (++budget.nodes > SCENE_LIMITS.maxNodes) fail(SceneErrorCode.TOO_MANY_NODES);
  if (!isPlainObject(raw)) fail(SceneErrorCode.NODE_INVALID);

  const node = raw as Record<string, unknown>;
  switch (node.kind) {
    case "metric":
      return compact({
        kind: "metric" as const,
        value: num(node.value),
        label: optText(node.label),
        format: optFormat(node.format),
        delta: optNum(node.delta),
        deltaGood: oneOf(node.deltaGood, ["up", "down"] as const),
        caption: optText(node.caption),
        tone: optTone(node.tone),
      });

    case "series":
      return compact({
        kind: "series" as const,
        mark: oneOf(node.mark, SERIES_MARKS) ?? fail(SceneErrorCode.ENUM_INVALID),
        series: arrayOf(node.series, SCENE_LIMITS.maxSeries).map(parseSeries),
        stacked: optBool(node.stacked),
        format: optFormat(node.format),
        xLabel: optText(node.xLabel),
        yLabel: optText(node.yLabel),
        showLegend: optBool(node.showLegend),
        labels: oneOf(node.labels, SERIES_LABELS),
        target: optNum(node.target),
        targetLabel: optText(node.targetLabel),
        emphasis: optNum(node.emphasis),
        horizontal: optBool(node.horizontal),
      });

    case "timeline": {
      const lanes: LaneBudget = { lanes: 0 };
      return compact({
        kind: "timeline" as const,
        lanes: asList(node.lanes).map((lane) => parseLane(lane, 0, lanes)),
        start: optNum(node.start),
        end: optNum(node.end),
        scale: oneOf(node.scale, ["day", "week", "month", "quarter"] as const),
        now: optNum(node.now),
      });
    }

    case "funnel":
      return compact({
        kind: "funnel" as const,
        stages: arrayOf(node.stages, SCENE_LIMITS.maxStages).map((stage) => {
          if (!isPlainObject(stage)) fail(SceneErrorCode.NODE_INVALID);
          return compact({
            label: text((stage as Record<string, unknown>).label),
            value: num((stage as Record<string, unknown>).value),
            tone: optTone((stage as Record<string, unknown>).tone),
          });
        }),
        format: optFormat(node.format),
      });

    case "progress":
      return compact({
        kind: "progress" as const,
        value: num(node.value),
        min: optNum(node.min),
        max: optNum(node.max),
        label: optText(node.label),
        caption: optText(node.caption),
        tone: optTone(node.tone),
        format: optFormat(node.format),
        target: optNum(node.target),
      });

    case "matrix":
      return compact({
        kind: "matrix" as const,
        cells: arrayOf(node.cells, SCENE_LIMITS.maxCells).map(parseCell),
        max: optNum(node.max),
        xLabels:
          node.xLabels === undefined
            ? undefined
            : arrayOf(node.xLabels, SCENE_LIMITS.maxCells).map(text),
        yLabels:
          node.yLabels === undefined
            ? undefined
            : arrayOf(node.yLabels, SCENE_LIMITS.maxCells).map(text),
        tone: optTone(node.tone),
      });

    case "table": {
      const columns = arrayOf(node.columns, SCENE_LIMITS.maxColumns).map(parseColumn);
      return compact({
        kind: "table" as const,
        columns,
        rows: arrayOf(node.rows, SCENE_LIMITS.maxRows).map((row) => parseRow(row, columns)),
      });
    }

    case "text":
      return compact({
        kind: "text" as const,
        text: text(node.text),
        variant: oneOf(node.variant, TEXT_VARIANTS),
        tone: optTone(node.tone),
      });

    case "empty":
      return compact({
        kind: "empty" as const,
        message: optText(node.message),
      });

    case "stack": {
      // Bounded by the node budget rather than an array cap, so that a scene
      // which is simply too big reports as TOO_MANY_NODES wherever it overflows.
      const children = asList(node.children).map((child) => parseNode(child, depth + 1, budget));
      return compact({
        kind: "stack" as const,
        direction: oneOf(node.direction, STACK_DIRECTIONS) ?? fail(SceneErrorCode.ENUM_INVALID),
        children,
        gap: oneOf(node.gap, ["none", "sm", "md"] as const),
        weights:
          node.weights === undefined
            ? undefined
            : asList(node.weights).slice(0, children.length).map(num),
      });
    }

    default:
      return fail(SceneErrorCode.NODE_KIND_UNKNOWN);
  }
};

/**
 * Validate and rebuild a widget's output.
 *
 * Returns a fresh `SceneSpec` on success, or a stable machine code the error
 * tile can localize. It never throws for bad input — a broken widget renders an
 * error tile, it does not take the canvas down.
 */
export function validateScene(raw: unknown): SceneValidation {
  try {
    if (!isPlainObject(raw)) fail(SceneErrorCode.NOT_AN_OBJECT);
    const spec = raw as Record<string, unknown>;

    const version = spec.v;
    if (typeof version !== "number" || version > WIDGET_API_VERSION) {
      fail(SceneErrorCode.API_VERSION_UNSUPPORTED);
    }

    return {
      ok: true,
      spec: { v: WIDGET_API_VERSION, scene: parseNode(spec.scene, 0, { nodes: 0 }) },
    };
  } catch (error) {
    if (error instanceof SceneError) return { ok: false, code: error.code };
    return { ok: false, code: SceneErrorCode.NODE_INVALID };
  }
}
