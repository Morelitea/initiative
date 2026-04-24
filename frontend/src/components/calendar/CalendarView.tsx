import { useCallback, useMemo } from "react";
import { useTranslation } from "react-i18next";
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

import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { PropertyValueCell } from "@/components/properties/PropertyValueCell";
import { nonEmptyPropertySummaries } from "@/components/properties/propertyHelpers";
import { getInitials } from "@/lib/initials";
import { resolveUploadUrl } from "@/lib/uploadUrl";
import { cn } from "@/lib/utils";
import type { PropertySummary } from "@/api/generated/initiativeAPI.schemas";

// ---------------------------------------------------------------------------
// Public types
// ---------------------------------------------------------------------------

export type CalendarViewMode = "day" | "week" | "month" | "year" | "list";

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
  /** Any extra data the consumer wants to pass through */
  meta?: Record<string, unknown>;
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
        <p className="text-lg font-semibold capitalize">{periodLabel}</p>
      </div>

      {/* Right: view mode switcher */}
      <TooltipProvider delayDuration={300}>
        <div
          className="bg-muted flex items-center gap-0.5 rounded-lg p-1"
          role="group"
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
                      "inline-flex items-center justify-center rounded-md px-2 py-1.5 text-sm font-medium transition-colors",
                      "hover:text-accent-foreground focus-visible:ring-ring focus-visible:ring-1 focus-visible:outline-none",
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
        </div>
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
}: {
  entries: CalendarEntry[];
  focusDate: Date;
  weekStartsOn: 0 | 1 | 2 | 3 | 4 | 5 | 6;
  onEntryClick?: (entry: CalendarEntry) => void;
  onSlotClick?: (date: Date) => void;
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
        <div className="text-muted-foreground grid grid-cols-7 text-center text-[11px] font-semibold uppercase sm:text-xs">
          {weekdayLabels.map((day) => (
            <div key={day} className="py-2">
              {day}
            </div>
          ))}
        </div>

        {/* Week rows */}
        <div className="bg-border space-y-px rounded-lg border">
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
                      <div
                        key={key}
                        role={onSlotClick ? "button" : undefined}
                        tabIndex={onSlotClick ? 0 : undefined}
                        className={cn(
                          "bg-card flex flex-col gap-0.5 p-1.5 text-left text-xs",
                          !isSameMonth(day, focusDate) && "bg-muted/40 text-muted-foreground",
                          isToday(day) && "ring-primary/80 ring-2",
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
                          <span className="text-sm font-medium">{format(day, "d")}</span>
                          {isToday(day) && (
                            <span className="text-primary text-[10px] font-semibold uppercase">
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
                            <button
                              key={entry.id}
                              type="button"
                              className={cn(
                                "flex w-full items-center gap-1 text-left text-[11px] leading-tight",
                                onEntryClick
                                  ? "hover:bg-accent cursor-pointer rounded px-0.5"
                                  : "cursor-default"
                              )}
                              onClick={(e) => {
                                e.stopPropagation();
                                onEntryClick?.(entry);
                              }}
                            >
                              <span
                                className="h-2 w-2 shrink-0 rounded-full"
                                style={{ backgroundColor: entry.color || "var(--primary)" }}
                              />
                              <span className="text-muted-foreground shrink-0 text-[10px]">
                                {entry.allDay ? "" : formatTime(start)}
                              </span>
                              <span className="truncate">{entry.title}</span>
                            </button>
                          );
                        })}
                        {overflow > 0 && (
                          <p className="text-muted-foreground text-[10px]">
                            {t("common:calendar.more", { count: overflow })}
                          </p>
                        )}
                      </div>
                    );
                  })}
                </div>

                {/* Spanning bars — absolutely positioned over the grid */}
                {spans.map((span) => {
                  const leftPct = (span.startCol / 7) * 100;
                  const widthPct = (span.spanCols / 7) * 100;
                  // Offset below the day number line (~24px)
                  const top = 24 + span.lane * (SPAN_BAR_HEIGHT + SPAN_BAR_GAP);

                  return (
                    <button
                      key={`${span.entry.id}-${dateKey(week[span.startCol])}`}
                      type="button"
                      className={cn(
                        "absolute z-10 flex items-center gap-1 overflow-hidden rounded px-2 text-[11px] font-medium text-white",
                        onEntryClick ? "cursor-pointer hover:brightness-90" : "cursor-default"
                      )}
                      style={{
                        left: `calc(${leftPct}% + 4px)`,
                        width: `calc(${widthPct}% - 8px)`,
                        top,
                        height: SPAN_BAR_HEIGHT,
                        backgroundColor: span.entry.color || "var(--primary)",
                      }}
                      onClick={(e) => {
                        e.stopPropagation();
                        onEntryClick?.(span.entry);
                      }}
                    >
                      <span className={cn("truncate", !span.showTitle && "opacity-70")}>
                        {span.entry.title}
                      </span>
                    </button>
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
}: {
  entries: CalendarEntry[];
  focusDate: Date;
  weekStartsOn: 0 | 1 | 2 | 3 | 4 | 5 | 6;
  onEntryClick?: (entry: CalendarEntry) => void;
  onSlotClick?: (date: Date) => void;
}) {
  const { t } = useTranslation(["common", "dates"]);

  const weekDays = useMemo(() => {
    const start = startOfWeek(focusDate, { weekStartsOn });
    return eachDayOfInterval({ start, end: addDays(start, 6) });
  }, [focusDate, weekStartsOn]);

  const { spans, singleDay } = useMemo(
    () => computeSpanPlacements(weekDays, entries),
    [weekDays, entries]
  );

  // Build timed entries by date (single-day non-all-day entries only)
  const timedByDate = useMemo(() => {
    const map = new Map<string, CalendarEntry[]>();
    for (const [key, dayEntries] of singleDay) {
      map.set(
        key,
        dayEntries.filter((e) => !e.allDay)
      );
    }
    return map;
  }, [singleDay]);

  // Also collect single-day all-day entries for the span area
  const allDaySingles = useMemo(() => {
    const result: SpanPlacement[] = [];
    for (const [key, dayEntries] of singleDay) {
      const col = weekDays.findIndex((d) => dateKey(d) === key);
      if (col === -1) continue;
      for (const entry of dayEntries) {
        if (entry.allDay) {
          result.push({ entry, startCol: col, spanCols: 1, lane: 0, showTitle: true });
        }
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
                  "flex flex-col items-center py-2 text-xs font-medium",
                  isToday(day) && "text-primary"
                )}
              >
                <span className="text-muted-foreground uppercase">
                  {t(`dates:weekdaysShort.${dayKey}`)}
                </span>
                <span
                  className={cn(
                    "mt-0.5 flex h-7 w-7 items-center justify-center rounded-full text-sm font-semibold",
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
            <div className="text-muted-foreground flex items-start justify-end pt-1 pr-2 text-[10px]">
              {t("common:calendar.allDay")}
            </div>
            <div className="relative col-span-7" style={{ height: spanAreaHeight + 4 }}>
              {allSpans.spans.map((span) => {
                const leftFrac = span.startCol / 7;
                const widthFrac = span.spanCols / 7;
                const top = span.lane * (SPAN_BAR_HEIGHT + SPAN_BAR_GAP) + 2;
                return (
                  <button
                    key={`${span.entry.id}-${span.startCol}`}
                    type="button"
                    className={cn(
                      "absolute z-10 flex items-center gap-1 overflow-hidden rounded px-2 text-[11px] font-medium text-white",
                      onEntryClick ? "cursor-pointer hover:brightness-90" : "cursor-default"
                    )}
                    style={{
                      left: `calc(${leftFrac * 100}% + 2px)`,
                      width: `calc(${widthFrac * 100}% - 4px)`,
                      top,
                      height: SPAN_BAR_HEIGHT,
                      backgroundColor: span.entry.color || "var(--primary)",
                    }}
                    onClick={(e) => {
                      e.stopPropagation();
                      onEntryClick?.(span.entry);
                    }}
                  >
                    <span className="truncate">{span.entry.title}</span>
                  </button>
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
                className="text-muted-foreground flex items-start justify-end border-b pt-1 pr-2 text-[10px]"
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
              const { start, end } = parseEntry(entry);
              const sH = getHours(start) + getMinutes(start) / 60;
              const eH = getHours(end) + getMinutes(end) / 60;
              dayBlocks.push({ entry, startHour: sH, endHour: eH <= sH ? sH + 1 : eH, lane: 0 });
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
                {/* Hour slot backgrounds */}
                {hours.map((hour) => (
                  <div
                    key={hour}
                    className={cn("border-b", onSlotClick && "hover:bg-accent/30 cursor-pointer")}
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
                    <button
                      key={block.entry.id}
                      type="button"
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
                      onClick={(e) => {
                        e.stopPropagation();
                        onEntryClick?.(block.entry);
                      }}
                    >
                      <div className="flex flex-col px-1.5 py-0.5">
                        <span className="truncate font-medium">{block.entry.title}</span>
                        {height >= 32 && (
                          <span className="text-muted-foreground text-[10px]">
                            {formatTime(parseEntry(block.entry).start)} –{" "}
                            {formatTime(parseEntry(block.entry).end)}
                          </span>
                        )}
                      </div>
                    </button>
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
}: {
  entries: CalendarEntry[];
  focusDate: Date;
  onEntryClick?: (entry: CalendarEntry) => void;
  onSlotClick?: (date: Date) => void;
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
      const { start, end } = parseEntry(entry);
      const sH = getHours(start) + getMinutes(start) / 60;
      const eH = getHours(end) + getMinutes(end) / 60;
      result.push({ entry, startHour: sH, endHour: eH <= sH ? sH + 1 : eH, lane: 0 });
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
  }, [timedEntries]);

  return (
    <div className="space-y-3">
      {/* All-day section */}
      {allDayEntries.length > 0 ? (
        <div className="space-y-1 border-b pb-3">
          <p className="text-muted-foreground text-xs font-semibold uppercase">
            {t("common:calendar.allDay")}
          </p>
          {allDayEntries.map((entry) => (
            <button
              key={entry.id}
              type="button"
              className={cn(
                "flex w-full items-center gap-1.5 rounded px-2 py-1 text-left text-[11px] font-medium text-white transition-colors",
                onEntryClick ? "cursor-pointer hover:brightness-90" : "cursor-default"
              )}
              style={{
                backgroundColor: entry.color || "var(--primary)",
              }}
              onClick={() => onEntryClick?.(entry)}
            >
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
              className="text-muted-foreground flex items-start justify-end border-b pt-1 pr-3 text-[10px]"
              style={{ height: ROW_HEIGHT }}
            >
              {formatHourLabel(hour)}
            </div>
          ))}
        </div>

        {/* Content column — relative container for positioned blocks */}
        <div className="relative border-l">
          {/* Clickable hour slot backgrounds */}
          {hours.map((hour) => (
            <div
              key={hour}
              className={cn("border-b", onSlotClick && "hover:bg-accent/30 cursor-pointer")}
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
              <button
                key={block.entry.id}
                type="button"
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
                onClick={(e) => {
                  e.stopPropagation();
                  onEntryClick?.(block.entry);
                }}
              >
                <div className="flex flex-col px-2 py-1">
                  <span className="truncate font-medium">{block.entry.title}</span>
                  <span className="text-muted-foreground text-[10px]">
                    {formatTime(parseEntry(block.entry).start)} –{" "}
                    {formatTime(parseEntry(block.entry).end)}
                  </span>
                </div>
              </button>
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
            <p className="text-sm font-semibold">{t(`dates:months.${monthIndex}`)}</p>
            {/* Mini weekday header */}
            <div className="grid grid-cols-7 text-center">
              {weekdayLabelsShort.map((label, i) => (
                <div key={i} className="text-muted-foreground py-0.5 text-[9px] font-medium">
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
                      isToday(day) && inMonth && "bg-primary text-primary-foreground font-bold"
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
                            key={i}
                            className="h-1 w-1 rounded-full"
                            style={{ backgroundColor: entry.color || "var(--primary)" }}
                          />
                        ))}
                      </div>
                    )}
                    {inMonth && dayEntries.length > 3 && (
                      <span
                        className="rounded-full px-1 text-[7px] leading-tight font-bold text-white"
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
      <div className="text-muted-foreground flex flex-col items-center justify-center py-12 text-sm">
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
                isToday(displayDate) && "ring-primary/60 ring-1",
                onEntryClick ? "hover:bg-accent cursor-pointer" : "cursor-default"
              )}
              onClick={() => onEntryClick?.(entry)}
            >
              {/* Date column: day + month */}
              <div className="flex w-14 shrink-0 flex-col items-center pt-0.5 leading-tight">
                <span className="text-lg font-bold">{day}</span>
                <span className="text-muted-foreground text-[11px] uppercase">{month}</span>
              </div>

              {/* Weekday name */}
              <span className="text-muted-foreground w-24 shrink-0 pt-1 text-xs">{weekday}</span>

              {/* Color dot */}
              <span
                className="bg-muted-foreground mt-1.5 h-3 w-3 shrink-0 rounded-full"
                style={{ backgroundColor: entry.color || undefined }}
                aria-hidden="true"
              />

              {/* Title + description + property chips */}
              <div className="min-w-0 flex-1">
                <span className="truncate font-medium">{entry.title}</span>
                {entry.description && (
                  <p className="text-muted-foreground mt-0.5 line-clamp-2 text-xs">
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
                            key={i}
                            className="border-card h-6 w-6 border-2 text-[9px] font-semibold uppercase"
                          >
                            {src ? <AvatarImage src={src} alt={att.name} /> : null}
                            <AvatarFallback userId={att.userId}>
                              {getInitials(att.name)}
                            </AvatarFallback>
                          </Avatar>
                        );
                      })}
                      {entry.attendees.length > 4 && (
                        <Avatar className="border-card h-6 w-6 border-2 text-[9px] font-semibold">
                          <AvatarFallback>+{entry.attendees.length - 4}</AvatarFallback>
                        </Avatar>
                      )}
                    </div>
                  </TooltipTrigger>
                  <TooltipContent side="top">
                    <div className="space-y-0.5 text-xs">
                      {entry.attendees.map((att, i) => (
                        <div key={i}>{att.name}</div>
                      ))}
                    </div>
                  </TooltipContent>
                </Tooltip>
              )}

              {/* Time */}
              <span className="text-muted-foreground shrink-0 pt-1 text-xs">
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
  weekStartsOn = 0,
  isLoading = false,
  hideListView = false,
}: CalendarViewProps) => {
  const periodLabel = usePeriodLabel(viewMode, focusDate, weekStartsOn);

  if (isLoading) {
    return (
      <div className="bg-card space-y-4 rounded-xl border p-4 shadow-sm">
        <CalendarSkeleton />
      </div>
    );
  }

  return (
    <div className="bg-card space-y-4 rounded-xl border p-4 shadow-sm">
      <CalendarHeader
        viewMode={viewMode}
        onViewModeChange={onViewModeChange}
        focusDate={focusDate}
        onFocusDateChange={onFocusDateChange}
        periodLabel={periodLabel}
        hideListView={hideListView}
      />

      {viewMode === "month" ? (
        <MonthView
          entries={entries}
          focusDate={focusDate}
          weekStartsOn={weekStartsOn}
          onEntryClick={onEntryClick}
          onSlotClick={onSlotClick}
        />
      ) : null}

      {viewMode === "week" ? (
        <WeekView
          entries={entries}
          focusDate={focusDate}
          weekStartsOn={weekStartsOn}
          onEntryClick={onEntryClick}
          onSlotClick={onSlotClick}
        />
      ) : null}

      {viewMode === "day" ? (
        <DayView
          entries={entries}
          focusDate={focusDate}
          onEntryClick={onEntryClick}
          onSlotClick={onSlotClick}
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
    </div>
  );
};
