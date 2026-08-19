/**
 * The calendar arithmetic behind a timeline.
 *
 * Split out from the renderer for two reasons. It is the part worth testing on
 * its own — a tick that lands a day off is invisible in a screenshot and obvious
 * in an assertion — and it is the part that must run in the *viewer's* timezone.
 * A widget's clock is frozen and has no zone (see `dataShapes`), so "which day
 * is this, and where does the week start" can only be answered on this side.
 *
 * Everything here is local-time: `Date`'s own accessors carry the viewer's zone
 * and its daylight-saving shifts, so stepping a day never drifts an hour.
 */

import type { TimelineLane, TimelineNode } from "./sceneSpec";

const DAY = 86_400_000;

export type TimeUnit = "day" | "week" | "month" | "quarter" | "year";

/** The coarser unit drawn above each scale in the header's top tier. A Gantt
 *  header is two rows — "August" over its weeks — because a column of bare day
 *  numbers stops meaning anything the moment it wraps a month. */
const MAJOR_OF: Record<TimeUnit, TimeUnit> = {
  day: "month",
  week: "month",
  month: "year",
  quarter: "year",
  year: "year",
};

export interface AxisTick {
  at: number;
  unit: TimeUnit;
}

/** A stretch of the top tier — one month, one year — clipped to the window. */
export interface AxisSegment {
  /** The unit's true start, which is what gets labelled. */
  at: number;
  /** The visible part, which is what gets measured. */
  start: number;
  end: number;
}

export interface TimelineRange {
  start: number;
  end: number;
}

// --- calendar steps ---------------------------------------------------------

const startOfDay = (at: number): number => {
  const date = new Date(at);
  date.setHours(0, 0, 0, 0);
  return date.getTime();
};

/**
 * Which weekday a week starts on for this locale, as `Date#getDay` numbers it
 * (0 = Sunday). `getWeekInfo` is the standard answer and is not everywhere yet,
 * so an engine without it falls back to Sunday rather than to nothing.
 */
export function weekStartDay(locale?: string): number {
  try {
    const info = (
      new Intl.Locale(locale ?? "en") as Intl.Locale & {
        getWeekInfo?: () => { firstDay: number };
      }
    ).getWeekInfo?.();
    // ISO numbers Monday 1 … Sunday 7; `getDay` numbers Sunday 0 … Saturday 6.
    if (info && typeof info.firstDay === "number") return info.firstDay % 7;
  } catch {
    // An unparseable tag is not worth failing an axis over.
  }
  return 0;
}

const startOfWeek = (at: number, weekStart: number): number => {
  const date = new Date(startOfDay(at));
  date.setDate(date.getDate() - ((date.getDay() - weekStart + 7) % 7));
  return date.getTime();
};

const startOfMonth = (at: number): number => {
  const date = new Date(startOfDay(at));
  date.setDate(1);
  return date.getTime();
};

const startOfQuarter = (at: number): number => {
  const date = new Date(startOfMonth(at));
  date.setMonth(Math.floor(date.getMonth() / 3) * 3);
  return date.getTime();
};

const startOfYear = (at: number): number => {
  const date = new Date(startOfMonth(at));
  date.setMonth(0);
  return date.getTime();
};

/** The start of the unit containing `at`. */
export function floorToUnit(at: number, unit: TimeUnit, weekStart = 0): number {
  switch (unit) {
    case "day":
      return startOfDay(at);
    case "week":
      return startOfWeek(at, weekStart);
    case "month":
      return startOfMonth(at);
    case "quarter":
      return startOfQuarter(at);
    default:
      return startOfYear(at);
  }
}

/** `count` units on from `at`, which must already sit on a unit boundary.
 *  Calendar arithmetic, not millisecond arithmetic: months are uneven and days
 *  are not always 24 hours long. */
export function addUnits(at: number, unit: TimeUnit, count: number): number {
  const date = new Date(at);
  switch (unit) {
    case "day":
      date.setDate(date.getDate() + count);
      break;
    case "week":
      date.setDate(date.getDate() + count * 7);
      break;
    case "month":
      date.setMonth(date.getMonth() + count);
      break;
    case "quarter":
      date.setMonth(date.getMonth() + count * 3);
      break;
    default:
      date.setFullYear(date.getFullYear() + count);
  }
  return date.getTime();
}

/** Roughly how many units the window covers — used only to pick a stride, so an
 *  approximation across uneven months is fine. */
const unitsAcross = (range: TimelineRange, unit: TimeUnit): number => {
  const days = (range.end - range.start) / DAY;
  switch (unit) {
    case "day":
      return days;
    case "week":
      return days / 7;
    case "month":
      return days / 30.44;
    case "quarter":
      return days / 91.31;
    default:
      return days / 365.25;
  }
};

// --- window -----------------------------------------------------------------

/** Every instant a lane tree touches, baselines included. */
const spanExtent = (lanes: TimelineLane[]): TimelineRange | null => {
  let low = Number.POSITIVE_INFINITY;
  let high = Number.NEGATIVE_INFINITY;
  const visit = (lane: TimelineLane) => {
    for (const span of lane.spans) {
      if (span.start < low) low = span.start;
      if (span.end > high) high = span.end;
      if (span.baseline) {
        if (span.baseline.start < low) low = span.baseline.start;
        if (span.baseline.end > high) high = span.baseline.end;
      }
    }
    for (const child of lane.children ?? []) visit(child);
  };
  for (const lane of lanes) visit(lane);
  return Number.isFinite(low) ? { start: low, end: high } : null;
};

/**
 * The window the axis covers.
 *
 * An explicit window from the widget wins. Otherwise the spans are fitted and
 * then snapped out to whole units, which is what gives the axis clean labels —
 * a chart that begins mid-week starts its first column on a partial one, and
 * every tick after it reads as an arbitrary date.
 */
export function timelineWindow(node: TimelineNode, weekStart = 0): TimelineRange {
  if (node.start !== undefined && node.end !== undefined && node.end > node.start) {
    return { start: node.start, end: node.end };
  }
  const fitted = spanExtent(node.lanes);
  // Nothing dated at all: any window will do, and a day of it keeps every
  // downstream division honest.
  if (!fitted) return { start: 0, end: DAY };

  const unit = node.scale ?? "week";
  const start = floorToUnit(fitted.start, unit, weekStart);
  const end = Math.max(
    addUnits(floorToUnit(fitted.end, unit, weekStart), unit, 1),
    // A single instant has no width to scale against; give it one unit.
    addUnits(start, unit, 1)
  );
  return { start, end };
}

/** Where a moment sits across the window, as a percentage. Clamping is the
 *  caller's business — a bar that starts before the window should be cut off at
 *  the edge, not moved. */
export const positionIn = (range: TimelineRange, at: number): number =>
  ((at - range.start) / Math.max(1, range.end - range.start)) * 100;

// --- ticks ------------------------------------------------------------------

/** Beyond this the header is a smear, so the stride widens instead. Chosen for
 *  the narrowest tile a Gantt may be placed in (six grid columns). */
const DEFAULT_MAX_TICKS = 14;

/**
 * Gridline positions across the window, at unit boundaries.
 *
 * The requested scale is a density *hint*: a year asked for in days would be
 * 365 columns, so the step widens until the count fits. Boundaries stay real
 * either way — every tick is the start of a day, week, month or quarter, never
 * an evenly-divided slice of the range.
 */
export function axisTicks(
  range: TimelineRange,
  unit: TimeUnit,
  weekStart = 0,
  maxTicks = DEFAULT_MAX_TICKS
): AxisTick[] {
  const stride = Math.max(1, Math.ceil(unitsAcross(range, unit) / maxTicks));
  const ticks: AxisTick[] = [];
  let at = floorToUnit(range.start, unit, weekStart);
  while (at < range.start) at = addUnits(at, unit, stride);
  while (at < range.end && ticks.length <= maxTicks * 2) {
    ticks.push({ at, unit });
    at = addUnits(at, unit, stride);
  }
  return ticks;
}

/** How many top-tier segments are worth drawing before the row is unreadable. */
const MAX_SEGMENTS = 48;

/** The header's top tier: the coarser unit above `unit`, clipped to the window.
 *  Empty when there would be too many to label. */
export function majorSegments(
  range: TimelineRange,
  unit: TimeUnit,
  weekStart = 0
): { segments: AxisSegment[]; unit: TimeUnit } {
  const major = MAJOR_OF[unit];
  const segments: AxisSegment[] = [];
  let at = floorToUnit(range.start, major, weekStart);
  while (at < range.end && segments.length <= MAX_SEGMENTS) {
    const next = addUnits(at, major, 1);
    segments.push({
      at,
      start: Math.max(at, range.start),
      end: Math.min(next, range.end),
    });
    at = next;
  }
  return { segments: segments.length > MAX_SEGMENTS ? [] : segments, unit: major };
}

/** How many weekend bands are worth painting. Past this the shading is a wash
 *  over the whole chart and says nothing. */
const MAX_BANDS = 60;

/**
 * Saturday/Sunday stretches inside the window.
 *
 * Shading non-working time is what makes a five-day bar read as a working week
 * rather than as five of seven days. Returns nothing once the window is long
 * enough that the stripes would outnumber what they mark.
 */
export function weekendBands(range: TimelineRange): TimelineRange[] {
  const bands: TimelineRange[] = [];
  let at = startOfDay(range.start);
  while (at < range.end) {
    const next = addUnits(at, "day", 1);
    const weekday = new Date(at).getDay();
    if (weekday === 0 || weekday === 6) {
      const previous = bands[bands.length - 1];
      // Saturday and Sunday are one band, so the pair paints as one stripe.
      if (previous && previous.end === at) previous.end = Math.min(next, range.end);
      else bands.push({ start: Math.max(at, range.start), end: Math.min(next, range.end) });
      if (bands.length > MAX_BANDS) return [];
    }
    at = next;
  }
  return bands;
}

// --- lanes ------------------------------------------------------------------

export interface FlatLane {
  lane: TimelineLane;
  /** Position in the tree, e.g. `0.2.1` — the identity a fold state is keyed
   *  by. Lane labels repeat (two projects of the same name), so position is the
   *  only thing that identifies a row. */
  path: string;
  depth: number;
  hasChildren: boolean;
  expanded: boolean;
  /** 1-based, for `aria-posinset`/`aria-setsize` on the row. */
  position: number;
  setSize: number;
}

/**
 * The rows to draw, in order, with everything a folded lane hides left out.
 *
 * `isOpen` is asked per path rather than read off the lane, because whether a
 * row is open belongs to the viewer: the widget says what a lane *starts* as,
 * and every click after that is the reader's.
 */
export function flattenLanes(
  lanes: TimelineLane[],
  isOpen: (path: string, lane: TimelineLane) => boolean
): FlatLane[] {
  const out: FlatLane[] = [];
  const walk = (level: TimelineLane[], prefix: string, depth: number) => {
    level.forEach((lane, index) => {
      const path = prefix ? `${prefix}.${index}` : String(index);
      const children = lane.children ?? [];
      const expanded = children.length > 0 && isOpen(path, lane);
      out.push({
        lane,
        path,
        depth,
        hasChildren: children.length > 0,
        expanded,
        position: index + 1,
        setSize: level.length,
      });
      if (expanded) walk(children, path, depth + 1);
    });
  };
  walk(lanes, "", 0);
  return out;
}
