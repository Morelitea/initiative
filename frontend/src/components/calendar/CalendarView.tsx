import {
  DndContext,
  type DragEndEvent,
  DragOverlay,
  type DragStartEvent,
  MouseSensor,
  pointerWithin,
  TouchSensor,
  useDraggable,
  useDroppable,
  useSensor,
  useSensors,
} from "@dnd-kit/core";
import {
  addDays,
  addMonths,
  addWeeks,
  addYears,
  eachDayOfInterval,
  endOfMonth,
  endOfWeek,
  format,
  getHours,
  getMinutes,
  isSameMonth,
  isToday,
  parseISO,
  startOfDay,
  startOfMonth,
  startOfWeek,
} from "date-fns";
import {
  Calendar,
  CalendarDays,
  CalendarRange,
  ChevronLeft,
  ChevronRight,
  Clock,
  Grid3X3,
  List,
} from "lucide-react";
import type { CSSProperties, ReactNode } from "react";
import { useCallback, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import type { PropertySummary, TagSummary } from "@/api/generated/initiativeAPI.schemas";
import { PropertyValueCell } from "@/components/properties/PropertyValueCell";
import { nonEmptyPropertySummaries } from "@/components/properties/propertyHelpers";
import { TagBadge } from "@/components/tags/TagBadge";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { getInitials } from "@/lib/initials";
import { resolveUploadUrl } from "@/lib/uploadUrl";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Public types
// ---------------------------------------------------------------------------

export type CalendarViewMode = "day" | "week" | "month" | "year" | "list";

/** Shared `useViewPreference` scope key so every calendar (initiative events,
 *  My Tasks, Created Tasks) persists and restores the same chosen sub-view. */
export const CALENDAR_VIEW_MODE_KEY = "calendar:view-mode";

export type CalendarEntryAttendee = {
  name: string;
  /** Uploaded avatar path; needs ``resolveUploadUrl`` to become absolute.
   *  Preferred over ``avatarBase64`` when both are set. */
  avatarUrl?: string | null;
  /** Inline base64 data URL for users without an uploaded avatar.
   *  Rendered as-is (already a full data URL). */
  avatarBase64?: string | null;
  /** User id for the deterministic avatar tint. Optional because some
   *  entry sources (e.g. event summaries, which carry just attendee
   *  names) don't expose ids yet; those render a neutral fallback. */
  userId?: number | null;
};

/** Presentational marker for task entries: lets the calendar render a
 *  "Start"/"Due" label and a distinct dot so the two are easy to tell apart.
 *  Unset for events and same-day task spans. */
export type CalendarEntryKind = "start" | "due";

export type CalendarEntry = {
  id: number | string;
  title: string;
  description?: string | null;
  startAt: string; // ISO datetime
  endAt: string; // ISO datetime
  allDay?: boolean;
  color?: string | null;
  attendees?: CalendarEntryAttendee[];
  /** Custom property values attached to the underlying entity. Rendered as
   *  compact chips on the list view; other calendar views omit them. */
  properties?: PropertySummary[];
  /** Tags attached to the underlying entity. Rendered as badges on the list view. */
  tags?: TagSummary[];
  /** Presentational start/due marker (see CalendarEntryKind). */
  kind?: CalendarEntryKind;
  /** When false, the entry cannot be dragged to reschedule (default true). */
  draggable?: boolean;
  /** Any extra data the consumer wants to pass through */
  meta?: Record<string, unknown>;
};

/** Payload handed to ``onEntryReschedule`` after a drag drop. CalendarView
 *  computes the resulting absolute ISO start/end (duration preserved, and
 *  time-of-day preserved on date-only moves); the consumer routes it to the
 *  right mutation using ``entry.meta``/``entry.kind``. */
export type CalendarEntryReschedule = {
  entry: CalendarEntry;
  /** New absolute start, ISO. */
  startAt: string;
  /** New absolute end, ISO. Equals ``startAt`` for instant markers. */
  endAt: string;
  /** Which axis changed: a date-only move (month/week) or a time move (day). */
  mode: "day" | "time";
};

type CalendarViewProps = {
  entries: CalendarEntry[];
  /** Current view mode */
  viewMode: CalendarViewMode;
  onViewModeChange: (mode: CalendarViewMode) => void;
  /** The currently focused date (used to determine what month/week/day to show) */
  focusDate: Date;
  onFocusDateChange: (date: Date) => void;
  /** Called when user clicks an entry */
  onEntryClick?: (entry: CalendarEntry) => void;
  /** Called when user clicks an empty day/time slot to create */
  onSlotClick?: (date: Date) => void;
  /** Called when the user drags an entry to a new day (month/week) or hour
   *  (day). When omitted, drag-to-reschedule is disabled entirely. */
  onEntryReschedule?: (change: CalendarEntryReschedule) => void;
  /** Week start day from user preferences */
  weekStartsOn?: 0 | 1 | 2 | 3 | 4 | 5 | 6;
  /** Loading state */
  isLoading?: boolean;
  /** Hide the list view option (e.g. for tasks where list doesn't make sense) */
  hideListView?: boolean;
};

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const WEEKDAY_KEYS = [
  "sunday",
  "monday",
  "tuesday",
  "wednesday",
  "thursday",
  "friday",
  "saturday",
] as const;

const MAX_VISIBLE_ENTRIES = 3;
const ROW_HEIGHT = 40; // px per hour row in day/week views

/** Hours shown in day / week time grids */
const DAY_START_HOUR = 0;
const DAY_END_HOUR = 23;

type ViewModeLabel =
  | "calendar.day"
  | "calendar.week"
  | "calendar.month"
  | "calendar.year"
  | "calendar.list";

const VIEW_MODE_CONFIG: {
  mode: CalendarViewMode;
  icon: typeof Calendar;
  labelKey: ViewModeLabel;
}[] = [
  { mode: "day", icon: Calendar, labelKey: "calendar.day" },
  { mode: "week", icon: CalendarRange, labelKey: "calendar.week" },
  { mode: "month", icon: CalendarDays, labelKey: "calendar.month" },
  { mode: "year", icon: Grid3X3, labelKey: "calendar.year" },
  { mode: "list", icon: List, labelKey: "calendar.list" },
];

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function dateKey(d: Date): string {
  return format(d, "yyyy-MM-dd");
}

function parseEntry(entry: CalendarEntry): { start: Date; end: Date } {
  return { start: parseISO(entry.startAt), end: parseISO(entry.endAt) };
}

/**
 * Clip a timed entry to a single day, returning the fractional start/end hours
 * (0–24) of the portion that falls on `day`, or null when it doesn't overlap.
 * Multi-day timed events use this so each day renders only its slice: the start
 * day runs from its start time to midnight, any middle day fills 0–24, and the
 * end day runs from midnight to its end time.
 */
function daySegmentHours(
  day: Date,
  entry: CalendarEntry
): { startHour: number; endHour: number } | null {
  const { start, end } = parseEntry(entry);
  if (Number.isNaN(start.getTime())) return null;
  const safeEnd = Number.isNaN(end.getTime()) ? start : end;
  const dayStart = startOfDay(day);
  const nextDay = addDays(dayStart, 1);
  if (safeEnd <= dayStart || start >= nextDay) return null;
  const segStart = start < dayStart ? dayStart : start;
  const segEnd = safeEnd > nextDay ? nextDay : safeEnd;
  const startHour = (segStart.getTime() - dayStart.getTime()) / 3_600_000;
  let endHour = (segEnd.getTime() - dayStart.getTime()) / 3_600_000;
  if (endHour <= startHour) endHour = Math.min(startHour + 1, 24);
  return { startHour, endHour };
}

function formatTime(date: Date): string {
  const h = getHours(date);
  const m = getMinutes(date);
  const ampm = h >= 12 ? "pm" : "am";
  const hr = h % 12 || 12;
  return m === 0 ? `${hr}${ampm}` : `${hr}:${m.toString().padStart(2, "0")}${ampm}`;
}

function formatHourLabel(hour: number): string {
  if (hour === 0) return "12am";
  if (hour < 12) return `${hour}am`;
  if (hour === 12) return "12pm";
  return `${hour - 12}pm`;
}

/** i18n key for a task entry's start/due marker label. */
function kindLabelKey(kind: CalendarEntryKind): "calendar.start" | "calendar.due" {
  return kind === "start" ? "calendar.start" : "calendar.due";
}

// ---------------------------------------------------------------------------
// Drag-and-drop primitives
// ---------------------------------------------------------------------------

/** Identifies what a droppable target represents. ``day`` (month/week) moves
 *  the date and keeps the time; ``hour`` (day view) moves the time. */
type DropData = { type: "day"; dateKey: string } | { type: "hour"; hour: number; dateKey: string };

/**
 * An entry rendered as a ``<button>`` that doubles as a dnd-kit draggable.
 * When ``enabled`` is false it behaves exactly like a plain button (click to
 * select), so non-reschedulable calendars are unaffected.
 */
function DraggableEntryButton({
  entry,
  enabled,
  className,
  style,
  title,
  dragId,
  onSelect,
  children,
}: {
  entry: CalendarEntry;
  enabled: boolean;
  className?: string;
  style?: CSSProperties;
  title?: string;
  /** Override for the dnd-kit draggable id. Required where the same entry is
   *  rendered as more than one strip (e.g. a span crossing multiple week rows
   *  in month view) so each registration has a unique id. Defaults to the
   *  entry id. ``data.entry`` is unchanged, so reschedule routing is identical. */
  dragId?: string;
  onSelect?: (entry: CalendarEntry) => void;
  children: ReactNode;
}) {
  const canDrag = enabled && entry.draggable !== false;
  const { setNodeRef, listeners, attributes, isDragging } = useDraggable({
    id: dragId ?? String(entry.id),
    data: { entry },
    disabled: !canDrag,
  });
  return (
    <button
      ref={setNodeRef}
      type="button"
      title={title}
      className={cn(className, canDrag && "touch-none", isDragging && "opacity-30")}
      style={style}
      {...(canDrag ? attributes : {})}
      {...(canDrag ? listeners : {})}
      onClick={(e) => {
        e.stopPropagation();
        onSelect?.(entry);
      }}
    >
      {children}
    </button>
  );
}

/**
 * A ``<div>`` that doubles as a dnd-kit droppable while still forwarding the
 * slot's own click/keyboard handlers (used for ``onSlotClick``). Highlights on
 * hover-over during a drag.
 */
function DroppableDiv({
  dropId,
  data,
  disabled,
  className,
  overClassName,
  style,
  role,
  tabIndex,
  onClick,
  onKeyDown,
  children,
}: {
  dropId: string;
  data: DropData;
  disabled: boolean;
  className?: string;
  overClassName?: string;
  style?: CSSProperties;
  role?: "button";
  tabIndex?: number;
  onClick?: (e: React.MouseEvent<HTMLDivElement>) => void;
  onKeyDown?: (e: React.KeyboardEvent<HTMLDivElement>) => void;
  children?: ReactNode;
}) {
  const { setNodeRef, isOver } = useDroppable({ id: dropId, data, disabled });
  return (
    // biome-ignore lint/a11y/noStaticElementInteractions: role is set when interactive
    <div
      ref={setNodeRef}
      className={cn(className, isOver && !disabled && overClassName)}
      style={style}
      role={role}
      tabIndex={tabIndex}
      onClick={onClick}
      onKeyDown={onKeyDown}
    >
      {children}
    </div>
  );
}

function buildEntriesByDate(entries: CalendarEntry[]): Map<string, CalendarEntry[]> {
  const map = new Map<string, CalendarEntry[]>();
  for (const entry of entries) {
    const { start, end } = parseEntry(entry);
    if (Number.isNaN(start.getTime())) continue;

    // Place entry on every day it spans (start through end inclusive)
    const endDay = Number.isNaN(end.getTime()) ? start : end;
    const cursor = new Date(startOfDay(start));
    const last = startOfDay(endDay);
    // Safety cap to avoid runaway loops on bad data
    let iterations = 0;
    while (cursor <= last && iterations < 90) {
      const key = dateKey(cursor);
      const list = map.get(key) ?? [];
      list.push(entry);
      map.set(key, list);
      cursor.setDate(cursor.getDate() + 1);
      iterations++;
    }
  }
  return map;
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// Calendar Header
// ---------------------------------------------------------------------------

function CalendarHeader({
  viewMode,
  onViewModeChange,
  focusDate,
  onFocusDateChange,
  periodLabel,
  hideListView = false,
}: {
  viewMode: CalendarViewMode;
  onViewModeChange: (mode: CalendarViewMode) => void;
  focusDate: Date;
  onFocusDateChange: (date: Date) => void;
  periodLabel: string;
  hideListView?: boolean;
}) {
  const { t } = useTranslation(["common"]);

  const navigate = useCallback(
    (direction: "prev" | "next") => {
      const delta = direction === "prev" ? -1 : 1;
      switch (viewMode) {
        case "day":
          onFocusDateChange(addDays(focusDate, delta));
          break;
        case "week":
          onFocusDateChange(addWeeks(focusDate, delta));
          break;
        case "month":
        case "list":
          onFocusDateChange(addMonths(focusDate, delta));
          break;
        case "year":
          onFocusDateChange(addYears(focusDate, delta));
          break;
      }
    },
    [viewMode, focusDate, onFocusDateChange]
  );

  const goToToday = useCallback(() => {
    onFocusDateChange(new Date());
  }, [onFocusDateChange]);

  return (
    <div className="flex flex-wrap items-center justify-between gap-3 border-b pb-3">
      {/* Left: navigation */}
      <div className="flex items-center gap-2">
        <Button type="button" variant="outline" size="sm" onClick={goToToday}>
          {t("common:calendar.today")}
        </Button>
        <Button type="button" variant="outline" size="icon-sm" onClick={() => navigate("prev")}>
          <ChevronLeft className="h-4 w-4" aria-hidden="true" />
          <span className="sr-only">{t("common:previous")}</span>
        </Button>
        <Button type="button" variant="outline" size="icon-sm" onClick={() => navigate("next")}>
          <ChevronRight className="h-4 w-4" aria-hidden="true" />
          <span className="sr-only">{t("common:next")}</span>
        </Button>
        <p className="font-semibold text-lg capitalize">{periodLabel}</p>
      </div>

      {/* Right: view mode switcher */}
      <TooltipProvider delayDuration={300}>
        <fieldset
          className="flex items-center gap-0.5 rounded-lg bg-muted p-1"
          aria-label={t("common:calendar.viewMode")}
        >
          {VIEW_MODE_CONFIG.filter(({ mode }) => !(hideListView && mode === "list")).map(
            ({ mode, icon: Icon, labelKey }) => (
              <Tooltip key={mode}>
                <TooltipTrigger asChild>
                  <button
                    type="button"
                    aria-pressed={viewMode === mode}
                    className={cn(
                      "inline-flex items-center justify-center rounded-md px-2 py-1.5 font-medium text-sm transition-colors",
                      "hover:text-accent-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring",
                      viewMode === mode
                        ? "bg-background text-foreground shadow-sm"
                        : "text-muted-foreground hover:bg-accent/50"
                    )}
                    onClick={() => onViewModeChange(mode)}
                  >
                    <Icon className="h-4 w-4" aria-hidden="true" />
                    <span className="sr-only">{t(labelKey)}</span>
                  </button>
                </TooltipTrigger>
                <TooltipContent side="bottom">{t(labelKey)}</TooltipContent>
              </Tooltip>
            )
          )}
        </fieldset>
      </TooltipProvider>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Multi-day span layout helpers
// ---------------------------------------------------------------------------

type SpanPlacement = {
  entry: CalendarEntry;
  startCol: number; // 0-based column within the week row
  spanCols: number; // how many columns to span
  lane: number; // vertical slot index (for stacking)
  showTitle: boolean; // only show title on first visible day of span
};

/**
 * For a week row (7 days), compute which entries span multiple days and
 * assign them lanes so they don't overlap visually.
 */
function computeSpanPlacements(
  weekDays: Date[],
  entries: CalendarEntry[]
): { spans: SpanPlacement[]; singleDay: Map<string, CalendarEntry[]>; maxLane: number } {
  const spans: SpanPlacement[] = [];
  const singleDay = new Map<string, CalendarEntry[]>();
  const seen = new Set<string | number>();

  // Identify multi-day entries that touch this week
  const weekStart = startOfDay(weekDays[0]);
  const weekEnd = startOfDay(weekDays[6]);

  for (const entry of entries) {
    const { start, end } = parseEntry(entry);
    if (Number.isNaN(start.getTime())) continue;
    const entryStart = startOfDay(start);
    const entryEnd = startOfDay(Number.isNaN(end.getTime()) ? start : end);

    const isMultiDay = entryEnd > entryStart;

    if (!isMultiDay) {
      // Single-day entry — collect for per-cell rendering
      const key = dateKey(start);
      const dayInWeek = weekDays.some((d) => dateKey(d) === key);
      if (dayInWeek) {
        const list = singleDay.get(key) ?? [];
        list.push(entry);
        singleDay.set(key, list);
      }
      continue;
    }

    // Multi-day: does it overlap this week?
    if (entryEnd < weekStart || entryStart > weekEnd) continue;
    if (seen.has(entry.id)) continue;
    seen.add(entry.id);

    const clampedStart = entryStart < weekStart ? weekStart : entryStart;
    const clampedEnd = entryEnd > weekEnd ? weekEnd : entryEnd;

    const startCol = weekDays.findIndex((d) => dateKey(d) === dateKey(clampedStart));
    const endCol = weekDays.findIndex((d) => dateKey(d) === dateKey(clampedEnd));
    if (startCol === -1) continue;

    const spanCols = (endCol === -1 ? 6 : endCol) - startCol + 1;
    const showTitle = entryStart >= weekStart; // show title only when span starts in this week

    spans.push({ entry, startCol, spanCols, lane: 0, showTitle });
  }

  // Assign lanes (greedy: first-fit)
  spans.sort((a, b) => a.startCol - b.startCol || b.spanCols - a.spanCols);
  const laneEnds: number[] = []; // track where each lane's last span ends
  for (const span of spans) {
    let assigned = false;
    for (let i = 0; i < laneEnds.length; i++) {
      if (laneEnds[i] <= span.startCol) {
        span.lane = i;
        laneEnds[i] = span.startCol + span.spanCols;
        assigned = true;
        break;
      }
    }
    if (!assigned) {
      span.lane = laneEnds.length;
      laneEnds.push(span.startCol + span.spanCols);
    }
  }

  const maxLane = laneEnds.length;
  return { spans, singleDay, maxLane };
}

const SPAN_BAR_HEIGHT = 20; // px per lane
const SPAN_BAR_GAP = 2;

// ---------------------------------------------------------------------------
// Month View
// ---------------------------------------------------------------------------

function MonthView({
  entries,
  focusDate,
  weekStartsOn,
  onEntryClick,
  onSlotClick,
  dndEnabled = false,
}: {
  entries: CalendarEntry[];
  focusDate: Date;
  weekStartsOn: 0 | 1 | 2 | 3 | 4 | 5 | 6;
  onEntryClick?: (entry: CalendarEntry) => void;
  onSlotClick?: (date: Date) => void;
  dndEnabled?: boolean;
}) {
  const { t } = useTranslation(["common", "dates"]);

  const calendarDays = useMemo(() => {
    const start = startOfWeek(startOfMonth(focusDate), { weekStartsOn });
    const end = endOfWeek(endOfMonth(focusDate), { weekStartsOn });
    return eachDayOfInterval({ start, end });
  }, [focusDate, weekStartsOn]);

  const weekdayLabels = useMemo(() => {
    const labels = WEEKDAY_KEYS.map((key) => t(`dates:weekdaysShort.${key}`));
    return labels.slice(weekStartsOn).concat(labels.slice(0, weekStartsOn));
  }, [weekStartsOn, t]);

  // Split calendar into week rows
  const weekRows = useMemo(() => {
    const rows: Date[][] = [];
    for (let i = 0; i < calendarDays.length; i += 7) {
      rows.push(calendarDays.slice(i, i + 7));
    }
    return rows;
  }, [calendarDays]);

  // Pre-compute span placements for each week row
  const weekPlacements = useMemo(
    () => weekRows.map((week) => computeSpanPlacements(week, entries)),
    [weekRows, entries]
  );

  return (
    <div className="space-y-2 overflow-x-auto sm:overflow-visible">
      <div className="min-w-[700px] sm:min-w-0">
        {/* Weekday headers */}
        <div className="grid grid-cols-7 text-center font-semibold text-[11px] text-muted-foreground uppercase sm:text-xs">
          {weekdayLabels.map((day) => (
            <div key={day} className="py-2">
              {day}
            </div>
          ))}
        </div>

        {/* Week rows */}
        <div className="space-y-px rounded-lg border bg-border">
          {weekRows.map((week, weekIdx) => {
            const { spans, singleDay, maxLane } = weekPlacements[weekIdx];
            const spanAreaHeight = maxLane * (SPAN_BAR_HEIGHT + SPAN_BAR_GAP);

            return (
              <div key={dateKey(week[0])} className="relative">
                {/* Day cells */}
                <div className="grid grid-cols-7 gap-px">
                  {week.map((day) => {
                    const key = dateKey(day);
                    const daySingles = singleDay.get(key) ?? [];
                    const visibleSingles = daySingles.slice(0, MAX_VISIBLE_ENTRIES);
                    const overflow = daySingles.length - MAX_VISIBLE_ENTRIES;

                    return (
                      <DroppableDiv
                        key={key}
                        dropId={`day:${key}`}
                        data={{ type: "day", dateKey: key }}
                        disabled={!dndEnabled}
                        overClassName="ring-2 ring-primary/60 ring-inset"
                        role={onSlotClick ? "button" : undefined}
                        tabIndex={onSlotClick ? 0 : undefined}
                        className={cn(
                          "flex flex-col gap-0.5 bg-card p-1.5 text-left text-xs",
                          !isSameMonth(day, focusDate) && "bg-muted/40 text-muted-foreground",
                          isToday(day) && "ring-2 ring-primary/80",
                          onSlotClick && "cursor-pointer"
                        )}
                        style={{ minHeight: 80 + spanAreaHeight }}
                        onClick={(e) => {
                          if (
                            e.target === e.currentTarget ||
                            (e.target as HTMLElement).closest("[data-slot='day-number']")
                          ) {
                            onSlotClick?.(startOfDay(day));
                          }
                        }}
                        onKeyDown={(e) => {
                          if (e.key === "Enter" || e.key === " ") {
                            e.preventDefault();
                            onSlotClick?.(startOfDay(day));
                          }
                        }}
                      >
                        <div className="flex items-center justify-between" data-slot="day-number">
                          <span className="font-medium text-sm">{format(day, "d")}</span>
                          {isToday(day) && (
                            <span className="font-semibold text-[10px] text-primary uppercase">
                              {t("common:calendar.today")}
                            </span>
                          )}
                        </div>
                        {/* Spacer for span bars */}
                        {spanAreaHeight > 0 && <div style={{ height: spanAreaHeight }} />}
                        {/* Single-day timed entries: dot + time + title */}
                        {visibleSingles.map((entry) => {
                          const { start } = parseEntry(entry);
                          return (
                            <DraggableEntryButton
                              key={entry.id}
                              entry={entry}
                              enabled={dndEnabled}
                              onSelect={onEntryClick}
                              className={cn(
                                "flex w-full items-center gap-1 text-left text-[11px] leading-tight",
                                onEntryClick
                                  ? "cursor-pointer rounded px-0.5 hover:bg-accent"
                                  : "cursor-default"
                              )}
                            >
                              <span
                                className={cn(
                                  "h-2 w-2 shrink-0 rounded-full",
                                  entry.kind === "start" && "border-2 bg-transparent"
                                )}
                                style={
                                  entry.kind === "start"
                                    ? { borderColor: entry.color || "var(--primary)" }
                                    : { backgroundColor: entry.color || "var(--primary)" }
                                }
                              />
                              {entry.kind ? (
                                <span className="shrink-0 font-semibold text-[9px] text-muted-foreground uppercase">
                                  {t(`common:${kindLabelKey(entry.kind)}`)}
                                </span>
                              ) : (
                                <span className="shrink-0 text-[10px] text-muted-foreground">
                                  {entry.allDay ? "" : formatTime(start)}
                                </span>
                              )}
                              <span className="truncate">{entry.title}</span>
                            </DraggableEntryButton>
                          );
                        })}
                        {overflow > 0 && (
                          <p className="text-[10px] text-muted-foreground">
                            {t("common:calendar.more", { count: overflow })}
                          </p>
                        )}
                      </DroppableDiv>
                    );
                  })}
                </div>

                {/* Spanning bars — absolutely positioned over the grid */}
                {spans.map((span) => {
                  const leftPct = (span.startCol / 7) * 100;
                  const widthPct = (span.spanCols / 7) * 100;
                  // Offset below the day number line (~24px)
                  const top = 24 + span.lane * (SPAN_BAR_HEIGHT + SPAN_BAR_GAP);

                  // A span crossing multiple week rows renders one strip per
                  // row; disambiguate the dnd-kit id by week so registrations
                  // don't collide.
                  const weekDragKey = `${span.entry.id}-${dateKey(week[span.startCol])}`;

                  return (
                    <DraggableEntryButton
                      key={weekDragKey}
                      dragId={weekDragKey}
                      entry={span.entry}
                      enabled={dndEnabled}
                      onSelect={onEntryClick}
                      className={cn(
                        "absolute z-10 flex items-center gap-1 overflow-hidden rounded px-2 font-medium text-[11px] text-white",
                        onEntryClick ? "cursor-pointer hover:brightness-90" : "cursor-default"
                      )}
                      style={{
                        left: `calc(${leftPct}% + 4px)`,
                        width: `calc(${widthPct}% - 8px)`,
                        top,
                        height: SPAN_BAR_HEIGHT,
                        backgroundColor: span.entry.color || "var(--primary)",
                      }}
                    >
                      <span className={cn("truncate", !span.showTitle && "opacity-70")}>
                        {span.entry.title}
                      </span>
                    </DraggableEntryButton>
                  );
                })}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Week View
// ---------------------------------------------------------------------------

function WeekView({
  entries,
  focusDate,
  weekStartsOn,
  onEntryClick,
  onSlotClick,
  dndEnabled = false,
}: {
  entries: CalendarEntry[];
  focusDate: Date;
  weekStartsOn: 0 | 1 | 2 | 3 | 4 | 5 | 6;
  onEntryClick?: (entry: CalendarEntry) => void;
  onSlotClick?: (date: Date) => void;
  dndEnabled?: boolean;
}) {
  const { t } = useTranslation(["common", "dates"]);

  const weekDays = useMemo(() => {
    const start = startOfWeek(focusDate, { weekStartsOn });
    return eachDayOfInterval({ start, end: addDays(start, 6) });
  }, [focusDate, weekStartsOn]);

  // The top span bar holds ONLY all-day entries. Timed entries — including
  // multi-day ones — render as clipped blocks in each day's time grid below.
  const allDayEntries = useMemo(() => entries.filter((e) => e.allDay), [entries]);
  const timedEntries = useMemo(() => entries.filter((e) => !e.allDay), [entries]);

  const { spans, singleDay } = useMemo(
    () => computeSpanPlacements(weekDays, allDayEntries),
    [weekDays, allDayEntries]
  );

  // A timed entry shows on every day it overlaps (multi-day events repeat,
  // clipped to each day's slice via daySegmentHours).
  const timedByDate = useMemo(() => {
    const map = new Map<string, CalendarEntry[]>();
    for (const day of weekDays) {
      const list = timedEntries.filter((e) => daySegmentHours(day, e) !== null);
      if (list.length) map.set(dateKey(day), list);
    }
    return map;
  }, [weekDays, timedEntries]);

  // Single-day all-day entries shown as one-column chips in the span area.
  // (`singleDay` only holds all-day entries now, since computeSpanPlacements
  // was given the all-day subset.)
  const allDaySingles = useMemo(() => {
    const result: SpanPlacement[] = [];
    for (const [key, dayEntries] of singleDay) {
      const col = weekDays.findIndex((d) => dateKey(d) === key);
      if (col === -1) continue;
      for (const entry of dayEntries) {
        result.push({ entry, startCol: col, spanCols: 1, lane: 0, showTitle: true });
      }
    }
    return result;
  }, [singleDay, weekDays]);

  // Merge multi-day spans + single-day all-day into one list and re-lane
  const allSpans = useMemo(() => {
    const merged = [...spans, ...allDaySingles];
    merged.sort((a, b) => a.startCol - b.startCol || b.spanCols - a.spanCols);
    const laneEnds: number[] = [];
    for (const span of merged) {
      let assigned = false;
      for (let i = 0; i < laneEnds.length; i++) {
        if (laneEnds[i] <= span.startCol) {
          span.lane = i;
          laneEnds[i] = span.startCol + span.spanCols;
          assigned = true;
          break;
        }
      }
      if (!assigned) {
        span.lane = laneEnds.length;
        laneEnds.push(span.startCol + span.spanCols);
      }
    }
    return { spans: merged, maxLane: laneEnds.length };
  }, [spans, allDaySingles]);

  const spanAreaHeight = allSpans.maxLane * (SPAN_BAR_HEIGHT + SPAN_BAR_GAP);

  const hours = useMemo(() => {
    const result: number[] = [];
    for (let h = DAY_START_HOUR; h <= DAY_END_HOUR; h++) {
      result.push(h);
    }
    return result;
  }, []);

  return (
    <div className="overflow-x-auto">
      <div className="min-w-[700px]">
        {/* Column headers */}
        <div className="grid grid-cols-[60px_repeat(7,1fr)] border-b">
          <div /> {/* Time gutter */}
          {weekDays.map((day) => {
            const dayKey = WEEKDAY_KEYS[day.getDay()];
            return (
              <div
                key={dateKey(day)}
                className={cn(
                  "flex flex-col items-center py-2 font-medium text-xs",
                  isToday(day) && "text-primary"
                )}
              >
                <span className="text-muted-foreground uppercase">
                  {t(`dates:weekdaysShort.${dayKey}`)}
                </span>
                <span
                  className={cn(
                    "mt-0.5 flex h-7 w-7 items-center justify-center rounded-full font-semibold text-sm",
                    isToday(day) && "bg-primary text-primary-foreground"
                  )}
                >
                  {format(day, "d")}
                </span>
              </div>
            );
          })}
        </div>

        {/* All-day / multi-day spanning bar area */}
        {allSpans.spans.length > 0 && (
          <div className="grid grid-cols-[60px_repeat(7,1fr)] border-b">
            <div className="flex items-start justify-end pt-1 pr-2 text-[10px] text-muted-foreground">
              {t("common:calendar.allDay")}
            </div>
            <div className="relative col-span-7" style={{ height: spanAreaHeight + 4 }}>
              {allSpans.spans.map((span) => {
                const leftFrac = span.startCol / 7;
                const widthFrac = span.spanCols / 7;
                const top = span.lane * (SPAN_BAR_HEIGHT + SPAN_BAR_GAP) + 2;
                return (
                  <DraggableEntryButton
                    key={`${span.entry.id}-${span.startCol}`}
                    dragId={`${span.entry.id}-${span.startCol}`}
                    entry={span.entry}
                    enabled={dndEnabled}
                    onSelect={onEntryClick}
                    className={cn(
                      "absolute z-10 flex items-center gap-1 overflow-hidden rounded px-2 font-medium text-[11px] text-white",
                      onEntryClick ? "cursor-pointer hover:brightness-90" : "cursor-default"
                    )}
                    style={{
                      left: `calc(${leftFrac * 100}% + 2px)`,
                      width: `calc(${widthFrac * 100}% - 4px)`,
                      top,
                      height: SPAN_BAR_HEIGHT,
                      backgroundColor: span.entry.color || "var(--primary)",
                    }}
                  >
                    {span.entry.kind && (
                      <span className="shrink-0 rounded-sm bg-white/25 px-1 font-semibold text-[9px] uppercase">
                        {t(`common:${kindLabelKey(span.entry.kind)}`)}
                      </span>
                    )}
                    <span className="truncate">{span.entry.title}</span>
                  </DraggableEntryButton>
                );
              })}
            </div>
          </div>
        )}

        {/* Time grid with positioned blocks */}
        <div className="grid max-h-[600px] grid-cols-[60px_repeat(7,1fr)] overflow-y-auto">
          {/* Time gutter */}
          <div>
            {hours.map((hour) => (
              <div
                key={hour}
                className="flex items-start justify-end border-b pt-1 pr-2 text-[10px] text-muted-foreground"
                style={{ height: ROW_HEIGHT }}
              >
                {formatHourLabel(hour)}
              </div>
            ))}
          </div>

          {/* Day columns — each is a relative container for positioned blocks */}
          {weekDays.map((day) => {
            const key = dateKey(day);
            const dayEntries = timedByDate.get(key) ?? [];

            // Compute positioned blocks for this day's timed entries
            const dayBlocks: {
              entry: CalendarEntry;
              startHour: number;
              endHour: number;
              lane: number;
            }[] = [];
            for (const entry of dayEntries) {
              const seg = daySegmentHours(day, entry);
              if (!seg) continue;
              dayBlocks.push({ entry, startHour: seg.startHour, endHour: seg.endHour, lane: 0 });
            }
            dayBlocks.sort(
              (a, b) =>
                a.startHour - b.startHour || b.endHour - b.startHour - (a.endHour - a.startHour)
            );
            const laneEnds: number[] = [];
            for (const block of dayBlocks) {
              let assigned = false;
              for (let i = 0; i < laneEnds.length; i++) {
                if (laneEnds[i] <= block.startHour) {
                  block.lane = i;
                  laneEnds[i] = block.endHour;
                  assigned = true;
                  break;
                }
              }
              if (!assigned) {
                block.lane = laneEnds.length;
                laneEnds.push(block.endHour);
              }
            }
            const dayMaxLane = Math.max(laneEnds.length, 1);

            return (
              <div key={key} className="relative border-l">
                {/* Hour slots — droppable so a timed entry dropped here moves
                    to this column's day AND this hour. */}
                {hours.map((hour) => (
                  <DroppableDiv
                    key={hour}
                    dropId={`week-slot:${key}:${hour}`}
                    data={{ type: "hour", hour, dateKey: key }}
                    disabled={!dndEnabled}
                    overClassName="bg-primary/10"
                    className={cn("border-b", onSlotClick && "cursor-pointer hover:bg-accent/30")}
                    style={{ height: ROW_HEIGHT }}
                    role={onSlotClick ? "button" : undefined}
                    tabIndex={onSlotClick ? 0 : undefined}
                    onClick={() => {
                      const slotDate = new Date(day);
                      slotDate.setHours(hour, 0, 0, 0);
                      onSlotClick?.(slotDate);
                    }}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        const slotDate = new Date(day);
                        slotDate.setHours(hour, 0, 0, 0);
                        onSlotClick?.(slotDate);
                      }
                    }}
                  />
                ))}

                {/* Positioned timed event blocks */}
                {dayBlocks.map((block) => {
                  const top = (block.startHour - DAY_START_HOUR) * ROW_HEIGHT;
                  const height = Math.max((block.endHour - block.startHour) * ROW_HEIGHT, 20);
                  const lanePct = (1 / dayMaxLane) * 100;
                  const leftPct = (block.lane / dayMaxLane) * 100;

                  return (
                    // A multi-day timed event renders one block per day, so the
                    // dnd-kit id must include the day to stay unique (data.entry
                    // is unchanged, so reschedule routing is identical).
                    <DraggableEntryButton
                      key={`${block.entry.id}-${key}`}
                      dragId={`${block.entry.id}-${key}`}
                      entry={block.entry}
                      enabled={dndEnabled}
                      onSelect={onEntryClick}
                      className={cn(
                        "absolute z-10 flex overflow-hidden rounded-r border text-left text-[11px] transition-colors",
                        onEntryClick ? "cursor-pointer hover:brightness-90" : "cursor-default"
                      )}
                      style={{
                        top,
                        height,
                        left: `calc(${leftPct}% + 2px)`,
                        width: `calc(${lanePct}% - 4px)`,
                        borderLeft: `3px solid ${block.entry.color || "var(--primary)"}`,
                        backgroundColor: "var(--card)",
                        boxShadow: "0 1px 3px rgba(0,0,0,0.1)",
                      }}
                    >
                      <div className="flex flex-col px-1.5 py-0.5">
                        <span className="truncate font-medium">{block.entry.title}</span>
                        {height >= 32 && (
                          <span className="text-[10px] text-muted-foreground">
                            {formatTime(parseEntry(block.entry).start)} –{" "}
                            {formatTime(parseEntry(block.entry).end)}
                          </span>
                        )}
                      </div>
                    </DraggableEntryButton>
                  );
                })}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Day View
// ---------------------------------------------------------------------------

function DayView({
  entries,
  focusDate,
  onEntryClick,
  onSlotClick,
  dndEnabled = false,
}: {
  entries: CalendarEntry[];
  focusDate: Date;
  onEntryClick?: (entry: CalendarEntry) => void;
  onSlotClick?: (date: Date) => void;
  dndEnabled?: boolean;
}) {
  const { t } = useTranslation(["common"]);

  const key = dateKey(focusDate);
  const entriesByDate = useMemo(() => buildEntriesByDate(entries), [entries]);
  const dayEntries = entriesByDate.get(key) ?? [];

  const allDayEntries = dayEntries.filter((e) => e.allDay);
  const timedEntries = dayEntries.filter((e) => !e.allDay);

  const hours = useMemo(() => {
    const result: number[] = [];
    for (let h = DAY_START_HOUR; h <= DAY_END_HOUR; h++) {
      result.push(h);
    }
    return result;
  }, []);

  // Compute positioned blocks for timed entries
  type TimedBlock = {
    entry: CalendarEntry;
    startHour: number; // fractional (e.g. 9.5 = 9:30)
    endHour: number;
    lane: number;
  };

  const { blocks, maxLane } = useMemo(() => {
    const result: TimedBlock[] = [];
    for (const entry of timedEntries) {
      const seg = daySegmentHours(focusDate, entry);
      if (!seg) continue;
      result.push({ entry, startHour: seg.startHour, endHour: seg.endHour, lane: 0 });
    }
    // Sort and assign lanes for overlapping
    result.sort(
      (a, b) => a.startHour - b.startHour || b.endHour - b.startHour - (a.endHour - a.startHour)
    );
    const laneEnds: number[] = [];
    for (const block of result) {
      let assigned = false;
      for (let i = 0; i < laneEnds.length; i++) {
        if (laneEnds[i] <= block.startHour) {
          block.lane = i;
          laneEnds[i] = block.endHour;
          assigned = true;
          break;
        }
      }
      if (!assigned) {
        block.lane = laneEnds.length;
        laneEnds.push(block.endHour);
      }
    }
    return { blocks: result, maxLane: Math.max(laneEnds.length, 1) };
  }, [timedEntries, focusDate]);

  return (
    <div className="space-y-3">
      {/* All-day section */}
      {allDayEntries.length > 0 ? (
        <div className="space-y-1 border-b pb-3">
          <p className="font-semibold text-muted-foreground text-xs uppercase">
            {t("common:calendar.allDay")}
          </p>
          {allDayEntries.map((entry) => (
            <button
              key={entry.id}
              type="button"
              className={cn(
                "flex w-full items-center gap-1.5 rounded px-2 py-1 text-left font-medium text-[11px] text-white transition-colors",
                onEntryClick ? "cursor-pointer hover:brightness-90" : "cursor-default"
              )}
              style={{
                backgroundColor: entry.color || "var(--primary)",
              }}
              onClick={() => onEntryClick?.(entry)}
            >
              {entry.kind && (
                <span className="shrink-0 rounded-sm bg-white/25 px-1 font-semibold text-[9px] uppercase">
                  {t(`common:${kindLabelKey(entry.kind)}`)}
                </span>
              )}
              <span className="truncate">{entry.title}</span>
            </button>
          ))}
        </div>
      ) : null}

      {/* Hour grid with positioned timed blocks */}
      <div className="grid max-h-[600px] grid-cols-[60px_1fr] overflow-y-auto">
        {/* Time gutter */}
        <div>
          {hours.map((hour) => (
            <div
              key={hour}
              className="flex items-start justify-end border-b pt-1 pr-3 text-[10px] text-muted-foreground"
              style={{ height: ROW_HEIGHT }}
            >
              {formatHourLabel(hour)}
            </div>
          ))}
        </div>

        {/* Content column — relative container for positioned blocks */}
        <div className="relative border-l">
          {/* Clickable + droppable hour slot backgrounds */}
          {hours.map((hour) => (
            <DroppableDiv
              key={hour}
              dropId={`hour:${key}:${hour}`}
              data={{ type: "hour", hour, dateKey: key }}
              disabled={!dndEnabled}
              overClassName="bg-primary/10"
              className={cn("border-b", onSlotClick && "cursor-pointer hover:bg-accent/30")}
              style={{ height: ROW_HEIGHT }}
              role={onSlotClick ? "button" : undefined}
              tabIndex={onSlotClick ? 0 : undefined}
              onClick={() => {
                const slotDate = new Date(focusDate);
                slotDate.setHours(hour, 0, 0, 0);
                onSlotClick?.(slotDate);
              }}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  const slotDate = new Date(focusDate);
                  slotDate.setHours(hour, 0, 0, 0);
                  onSlotClick?.(slotDate);
                }
              }}
            />
          ))}

          {/* Positioned timed event blocks */}
          {blocks.map((block) => {
            const top = (block.startHour - DAY_START_HOUR) * ROW_HEIGHT;
            const height = Math.max((block.endHour - block.startHour) * ROW_HEIGHT, 20);
            const lanePct = (1 / maxLane) * 100;
            const leftPct = (block.lane / maxLane) * 100;

            return (
              <DraggableEntryButton
                key={block.entry.id}
                entry={block.entry}
                enabled={dndEnabled}
                onSelect={onEntryClick}
                className={cn(
                  "absolute z-10 flex overflow-hidden rounded-r border text-left text-[11px] transition-colors",
                  onEntryClick ? "cursor-pointer hover:brightness-90" : "cursor-default"
                )}
                style={{
                  top,
                  height,
                  left: `calc(${leftPct}% + 2px)`,
                  width: `calc(${lanePct}% - 4px)`,
                  borderLeft: `3px solid ${block.entry.color || "var(--primary)"}`,
                  backgroundColor: "var(--card)",
                  boxShadow: "0 1px 3px rgba(0,0,0,0.1)",
                }}
              >
                <div className="flex flex-col px-2 py-1">
                  <span className="truncate font-medium">{block.entry.title}</span>
                  <span className="text-[10px] text-muted-foreground">
                    {formatTime(parseEntry(block.entry).start)} –{" "}
                    {formatTime(parseEntry(block.entry).end)}
                  </span>
                </div>
              </DraggableEntryButton>
            );
          })}
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Year View
// ---------------------------------------------------------------------------

function YearView({
  entries,
  focusDate,
  weekStartsOn,
  onFocusDateChange,
  onViewModeChange,
}: {
  entries: CalendarEntry[];
  focusDate: Date;
  weekStartsOn: 0 | 1 | 2 | 3 | 4 | 5 | 6;
  onFocusDateChange: (date: Date) => void;
  onViewModeChange: (mode: CalendarViewMode) => void;
}) {
  const { t } = useTranslation(["dates"]);

  const year = focusDate.getFullYear();

  const entriesByDate = useMemo(() => buildEntriesByDate(entries), [entries]);

  const months = useMemo(() => {
    return Array.from({ length: 12 }, (_, i) => new Date(year, i, 1));
  }, [year]);

  const weekdayLabelsShort = useMemo(() => {
    const labels = WEEKDAY_KEYS.map((key) => t(`dates:weekdaysShort.${key}`).charAt(0));
    return labels.slice(weekStartsOn).concat(labels.slice(0, weekStartsOn));
  }, [weekStartsOn, t]);

  return (
    <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4">
      {months.map((monthDate) => {
        const monthStart = startOfMonth(monthDate);
        const gridStart = startOfWeek(monthStart, { weekStartsOn });
        const gridEnd = endOfWeek(endOfMonth(monthDate), { weekStartsOn });
        const days = eachDayOfInterval({ start: gridStart, end: gridEnd });
        const monthIndex = (monthDate.getMonth() + 1) as
          | 1
          | 2
          | 3
          | 4
          | 5
          | 6
          | 7
          | 8
          | 9
          | 10
          | 11
          | 12;

        return (
          <div key={monthIndex} className="space-y-1">
            <p className="font-semibold text-sm">{t(`dates:months.${monthIndex}`)}</p>
            {/* Mini weekday header */}
            <div className="grid grid-cols-7 text-center">
              {weekdayLabelsShort.map((label) => (
                <div key={label} className="py-0.5 font-medium text-[9px] text-muted-foreground">
                  {label}
                </div>
              ))}
            </div>
            {/* Mini day grid */}
            <div className="grid grid-cols-7 text-center">
              {days.map((day) => {
                const key = dateKey(day);
                const dayEntries = entriesByDate.get(key) ?? [];
                const inMonth = isSameMonth(day, monthDate);

                return (
                  <button
                    key={key}
                    type="button"
                    className={cn(
                      "relative flex h-8 w-full flex-col items-center justify-start gap-0 rounded pt-0.5 text-[10px] transition-colors",
                      !inMonth && "text-transparent",
                      inMonth && "hover:bg-accent",
                      isToday(day) && inMonth && "bg-primary font-bold text-primary-foreground"
                    )}
                    disabled={!inMonth}
                    tabIndex={inMonth ? 0 : -1}
                    onClick={() => {
                      onFocusDateChange(day);
                      onViewModeChange("month");
                    }}
                  >
                    {format(day, "d")}
                    {inMonth && dayEntries.length > 0 && dayEntries.length <= 3 && (
                      <div className="flex gap-px">
                        {dayEntries.slice(0, 3).map((entry, i) => (
                          <span
                            key={entry.id}
                            className="h-1 w-1 rounded-full"
                            style={{ backgroundColor: entry.color || "var(--primary)" }}
                          />
                        ))}
                      </div>
                    )}
                    {inMonth && dayEntries.length > 3 && (
                      <span
                        className="rounded-full px-1 font-bold text-[7px] text-white leading-tight"
                        style={{ backgroundColor: "var(--primary)" }}
                      >
                        {dayEntries.length}
                      </span>
                    )}
                  </button>
                );
              })}
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// List View
// ---------------------------------------------------------------------------

function ListView({
  entries,
  focusDate,
  onEntryClick,
}: {
  entries: CalendarEntry[];
  focusDate: Date;
  onEntryClick?: (entry: CalendarEntry) => void;
}) {
  const { t } = useTranslation(["common"]);

  // Expand multi-day entries so each spanned day gets its own row
  type ListRow = { entry: CalendarEntry; displayDate: Date; isSpanDay: boolean };

  const rows = useMemo<ListRow[]>(() => {
    const monthStart = startOfMonth(focusDate);
    const monthEnd = endOfMonth(focusDate);
    const result: ListRow[] = [];

    for (const entry of entries) {
      const { start, end } = parseEntry(entry);
      if (Number.isNaN(start.getTime())) continue;

      const endDay = Number.isNaN(end.getTime()) ? start : end;
      const cursor = new Date(startOfDay(start));
      const last = startOfDay(endDay);
      let iterations = 0;

      while (cursor <= last && iterations < 90) {
        if (cursor >= startOfDay(monthStart) && cursor <= monthEnd) {
          const isFirstDay = iterations === 0;
          result.push({
            entry,
            displayDate: new Date(cursor),
            isSpanDay: !isFirstDay,
          });
        }
        cursor.setDate(cursor.getDate() + 1);
        iterations++;
      }
    }

    result.sort((a, b) => a.displayDate.getTime() - b.displayDate.getTime());
    return result;
  }, [entries, focusDate]);

  if (rows.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-12 text-muted-foreground text-sm">
        <Clock className="mb-2 h-8 w-8 opacity-50" />
        <p>{t("common:calendar.noEntries")}</p>
      </div>
    );
  }

  return (
    <TooltipProvider delayDuration={200}>
      <div className="space-y-1">
        {rows.map(({ entry, displayDate, isSpanDay }) => {
          const { start } = parseEntry(entry);
          const day = format(displayDate, "d");
          const month = format(displayDate, "MMM");
          const weekday = format(displayDate, "EEEE");

          return (
            <button
              key={`${entry.id}-${dateKey(displayDate)}`}
              type="button"
              className={cn(
                "flex w-full items-start gap-4 rounded-md border px-3 py-2.5 text-left text-sm transition-colors",
                isToday(displayDate) && "ring-1 ring-primary/60",
                onEntryClick ? "cursor-pointer hover:bg-accent" : "cursor-default"
              )}
              onClick={() => onEntryClick?.(entry)}
            >
              {/* Date column: day + month */}
              <div className="flex w-14 shrink-0 flex-col items-center pt-0.5 leading-tight">
                <span className="font-bold text-lg">{day}</span>
                <span className="text-[11px] text-muted-foreground uppercase">{month}</span>
              </div>

              {/* Weekday name */}
              <span className="w-24 shrink-0 pt-1 text-muted-foreground text-xs">{weekday}</span>

              {/* Color dot */}
              <span
                className="mt-1.5 h-3 w-3 shrink-0 rounded-full bg-muted-foreground"
                style={{ backgroundColor: entry.color || undefined }}
                aria-hidden="true"
              />

              {/* Title + description + property chips */}
              <div className="min-w-0 flex-1">
                {entry.kind && (
                  <span className="mr-1.5 rounded-sm bg-muted px-1 font-semibold text-[10px] text-muted-foreground uppercase">
                    {t(`common:${kindLabelKey(entry.kind)}`)}
                  </span>
                )}
                <span className="font-medium">{entry.title}</span>
                {entry.description && (
                  <p className="mt-0.5 line-clamp-2 text-muted-foreground text-xs">
                    {entry.description}
                  </p>
                )}
                {(() => {
                  const chips = nonEmptyPropertySummaries(entry.properties);
                  if (chips.length === 0) return null;
                  return (
                    <div className="mt-1 flex flex-wrap gap-1">
                      {chips.map((summary) => (
                        <PropertyValueCell
                          key={summary.property_id}
                          summary={summary}
                          variant="chip"
                        />
                      ))}
                    </div>
                  );
                })()}
                {entry.tags && entry.tags.length > 0 && (
                  <div className="mt-1 flex flex-wrap gap-1">
                    {entry.tags.slice(0, 3).map((tag) => (
                      <TagBadge key={tag.id} tag={tag} size="sm" />
                    ))}
                    {entry.tags.length > 3 && (
                      <span className="text-muted-foreground text-xs">
                        +{entry.tags.length - 3}
                      </span>
                    )}
                  </div>
                )}
              </div>

              {/* Attendee avatars */}
              {entry.attendees && entry.attendees.length > 0 && (
                <Tooltip>
                  <TooltipTrigger asChild>
                    <div className="flex shrink-0 -space-x-1.5 pt-0.5">
                      {entry.attendees.slice(0, 4).map((att, i) => {
                        const src =
                          resolveUploadUrl(att.avatarUrl) || att.avatarBase64 || undefined;
                        return (
                          <Avatar
                            key={att.userId}
                            className="h-6 w-6 border-2 border-card font-semibold text-[9px] uppercase"
                          >
                            {src ? <AvatarImage src={src} alt={att.name} /> : null}
                            <AvatarFallback userId={att.userId}>
                              {getInitials(att.name)}
                            </AvatarFallback>
                          </Avatar>
                        );
                      })}
                      {entry.attendees.length > 4 && (
                        <Avatar className="h-6 w-6 border-2 border-card font-semibold text-[9px]">
                          <AvatarFallback>+{entry.attendees.length - 4}</AvatarFallback>
                        </Avatar>
                      )}
                    </div>
                  </TooltipTrigger>
                  <TooltipContent side="top">
                    <div className="space-y-0.5 text-xs">
                      {entry.attendees.map((att) => (
                        <div key={att.userId}>{att.name}</div>
                      ))}
                    </div>
                  </TooltipContent>
                </Tooltip>
              )}

              {/* Time */}
              <span className="shrink-0 pt-1 text-muted-foreground text-xs">
                {entry.allDay || isSpanDay
                  ? t("common:calendar.allDay")
                  : `${formatTime(start)} – ${formatTime(parseEntry(entry).end)}`}
              </span>
            </button>
          );
        })}
      </div>
    </TooltipProvider>
  );
}

// ---------------------------------------------------------------------------
// Loading Skeleton
// ---------------------------------------------------------------------------

function CalendarSkeleton() {
  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Skeleton className="h-8 w-16" />
          <Skeleton className="h-8 w-8" />
          <Skeleton className="h-8 w-8" />
          <Skeleton className="h-6 w-40" />
        </div>
        <Skeleton className="h-8 w-48" />
      </div>
      <div className="grid grid-cols-7 gap-px">
        {Array.from({ length: 35 }).map((_, i) => (
          // biome-ignore lint/suspicious/noArrayIndexKey: This is a static skeleton layout, not dynamic data
          <Skeleton key={i} className="h-28 rounded-none" />
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Period Label
// ---------------------------------------------------------------------------

function usePeriodLabel(
  viewMode: CalendarViewMode,
  focusDate: Date,
  weekStartsOn: 0 | 1 | 2 | 3 | 4 | 5 | 6
): string {
  const { i18n } = useTranslation();

  return useMemo(() => {
    const locale = i18n.language;
    switch (viewMode) {
      case "day":
        return focusDate.toLocaleDateString(locale, {
          weekday: "long",
          month: "long",
          day: "numeric",
          year: "numeric",
        });
      case "week": {
        const weekStart = startOfWeek(focusDate, { weekStartsOn });
        const weekEnd = addDays(weekStart, 6);
        const startStr = weekStart.toLocaleDateString(locale, {
          month: "short",
          day: "numeric",
        });
        const endStr = weekEnd.toLocaleDateString(locale, {
          month: "short",
          day: "numeric",
          year: "numeric",
        });
        return `${startStr} \u2013 ${endStr}`;
      }
      case "month":
      case "list":
        return focusDate.toLocaleDateString(locale, {
          month: "long",
          year: "numeric",
        });
      case "year":
        return focusDate.getFullYear().toString();
    }
  }, [viewMode, focusDate, weekStartsOn, i18n.language]);
}

// ---------------------------------------------------------------------------
// Main Component
// ---------------------------------------------------------------------------

export const CalendarView = ({
  entries,
  viewMode,
  onViewModeChange,
  focusDate,
  onFocusDateChange,
  onEntryClick,
  onSlotClick,
  onEntryReschedule,
  weekStartsOn = 0,
  isLoading = false,
  hideListView = false,
}: CalendarViewProps) => {
  const periodLabel = usePeriodLabel(viewMode, focusDate, weekStartsOn);
  const dndEnabled = !!onEntryReschedule;
  const [activeEntry, setActiveEntry] = useState<CalendarEntry | null>(null);

  // A small move (>5px mouse, long-press on touch) starts a drag; a plain
  // click still selects the entry, so navigation keeps working.
  const sensors = useSensors(
    useSensor(MouseSensor, { activationConstraint: { distance: 5 } }),
    useSensor(TouchSensor, { activationConstraint: { delay: 200, tolerance: 8 } })
  );

  const handleDragStart = useCallback((event: DragStartEvent) => {
    setActiveEntry((event.active.data.current?.entry as CalendarEntry | undefined) ?? null);
  }, []);

  const handleDragEnd = useCallback(
    (event: DragEndEvent) => {
      setActiveEntry(null);
      const { active, over } = event;
      if (!over) return;
      const entry = active.data.current?.entry as CalendarEntry | undefined;
      const drop = over.data.current as DropData | undefined;
      if (!entry || !drop) return;

      const start = parseISO(entry.startAt);
      if (Number.isNaN(start.getTime())) return;
      const end = parseISO(entry.endAt);
      const durationMs = Number.isNaN(end.getTime()) ? 0 : end.getTime() - start.getTime();

      if (drop.type === "day") {
        // Change the date, keep the time-of-day (local midnight for all-day).
        const target = parseISO(`${drop.dateKey}T00:00:00`);
        const newStart = new Date(target);
        newStart.setHours(start.getHours(), start.getMinutes(), start.getSeconds(), 0);
        if (dateKey(newStart) === dateKey(start)) return; // no-op
        const newEnd = new Date(newStart.getTime() + durationMs);
        onEntryReschedule?.({
          entry,
          startAt: newStart.toISOString(),
          endAt: newEnd.toISOString(),
          mode: "day",
        });
        return;
      }

      // drop.type === "hour": set the date to the dropped column's day. Timed
      // entries also move to the dropped hour; all-day markers keep their
      // (midnight) time and only change date — so dropping a task start/due
      // marker into a week column reschedules its date. In day view the column
      // is always the focused day, so only the time changes.
      const targetDay = parseISO(`${drop.dateKey}T00:00:00`);
      const newStart = new Date(targetDay);
      if (entry.allDay) {
        newStart.setHours(start.getHours(), start.getMinutes(), start.getSeconds(), 0);
      } else {
        newStart.setHours(drop.hour, 0, 0, 0);
      }
      if (newStart.getTime() === start.getTime()) return; // no-op
      const newEnd = new Date(newStart.getTime() + durationMs);
      onEntryReschedule?.({
        entry,
        startAt: newStart.toISOString(),
        endAt: newEnd.toISOString(),
        mode: entry.allDay ? "day" : "time",
      });
    },
    [onEntryReschedule]
  );

  if (isLoading) {
    return (
      <div className="space-y-4 rounded-xl border bg-card p-4 shadow-sm">
        <CalendarSkeleton />
      </div>
    );
  }

  const views = (
    <>
      {viewMode === "month" ? (
        <MonthView
          entries={entries}
          focusDate={focusDate}
          weekStartsOn={weekStartsOn}
          onEntryClick={onEntryClick}
          onSlotClick={onSlotClick}
          dndEnabled={dndEnabled}
        />
      ) : null}

      {viewMode === "week" ? (
        <WeekView
          entries={entries}
          focusDate={focusDate}
          weekStartsOn={weekStartsOn}
          onEntryClick={onEntryClick}
          onSlotClick={onSlotClick}
          dndEnabled={dndEnabled}
        />
      ) : null}

      {viewMode === "day" ? (
        <DayView
          entries={entries}
          focusDate={focusDate}
          onEntryClick={onEntryClick}
          onSlotClick={onSlotClick}
          dndEnabled={dndEnabled}
        />
      ) : null}

      {viewMode === "year" ? (
        <YearView
          entries={entries}
          focusDate={focusDate}
          weekStartsOn={weekStartsOn}
          onFocusDateChange={onFocusDateChange}
          onViewModeChange={onViewModeChange}
        />
      ) : null}

      {viewMode === "list" ? (
        <ListView entries={entries} focusDate={focusDate} onEntryClick={onEntryClick} />
      ) : null}
    </>
  );

  return (
    <div className="space-y-4 rounded-xl border bg-card p-4 shadow-sm">
      <CalendarHeader
        viewMode={viewMode}
        onViewModeChange={onViewModeChange}
        focusDate={focusDate}
        onFocusDateChange={onFocusDateChange}
        periodLabel={periodLabel}
        hideListView={hideListView}
      />

      {dndEnabled ? (
        <DndContext
          sensors={sensors}
          collisionDetection={pointerWithin}
          onDragStart={handleDragStart}
          onDragEnd={handleDragEnd}
          onDragCancel={() => setActiveEntry(null)}
        >
          {views}
          <DragOverlay>
            {activeEntry ? (
              <div
                className="pointer-events-none flex items-center gap-1 rounded px-2 py-1 font-medium text-[11px] text-white shadow-lg"
                style={{ backgroundColor: activeEntry.color || "var(--primary)" }}
              >
                <span className="truncate">{activeEntry.title}</span>
              </div>
            ) : null}
          </DragOverlay>
        </DndContext>
      ) : (
        views
      )}
    </div>
  );
};
