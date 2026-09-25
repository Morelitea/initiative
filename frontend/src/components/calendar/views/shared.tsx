import { useDraggable, useDroppable } from "@dnd-kit/core";
import { addDays, format, parseISO, startOfDay } from "date-fns";
import type { CSSProperties, ReactNode } from "react";

import { UnreadDot } from "@/components/notifications/UnreadDot";
import { formatHourLabel, formatCompactTime as formatTime } from "@/lib/timeFormat";
import { cn } from "@/lib/utils";

import type { CalendarEntry, CalendarEntryKind } from "../CalendarView";

/** The props every view takes from the calendar around it. */
export type CalendarViewBaseProps = {
  entries: CalendarEntry[];
  focusDate: Date;
  onEntryClick?: (entry: CalendarEntry) => void;
};

/** The props of the views an entry can be dragged or a slot clicked in. */
export type CalendarGridViewProps = CalendarViewBaseProps & {
  onSlotClick?: (date: Date) => void;
  dndEnabled?: boolean;
};

export type WeekStartsOn = 0 | 1 | 2 | 3 | 4 | 5 | 6;

export const WEEKDAY_KEYS = [
  "sunday",
  "monday",
  "tuesday",
  "wednesday",
  "thursday",
  "friday",
  "saturday",
] as const;

export const SPAN_BAR_HEIGHT = 20; // px per lane
export const SPAN_BAR_GAP = 2;

const ROW_HEIGHT = 40; // px per hour row in day/week views

/** Hours shown in the day and week time grids. */
const HOURS = Array.from({ length: 24 }, (_, hour) => hour);

export function dateKey(d: Date): string {
  return format(d, "yyyy-MM-dd");
}

export function parseEntry(entry: CalendarEntry): { start: Date; end: Date } {
  return { start: parseISO(entry.startAt), end: parseISO(entry.endAt) };
}

/** i18n key for a task entry's start/due marker label. */
export function kindLabelKey(kind: CalendarEntryKind): "calendar.start" | "calendar.due" {
  return kind === "start" ? "calendar.start" : "calendar.due";
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

/**
 * Stack overlapping items into lanes, first fit: earliest first, the longer of
 * two that start together first. Sets each item's `lane` and returns how many
 * lanes it took.
 */
function assignLanes<T extends { lane: number }>(
  items: T[],
  startOf: (item: T) => number,
  endOf: (item: T) => number
): number {
  items.sort((a, b) => startOf(a) - startOf(b) || endOf(b) - startOf(b) - (endOf(a) - startOf(a)));
  const laneEnds: number[] = [];
  for (const item of items) {
    const free = laneEnds.findIndex((laneEnd) => laneEnd <= startOf(item));
    item.lane = free === -1 ? laneEnds.length : free;
    laneEnds[item.lane] = endOf(item);
  }
  return laneEnds.length;
}

/** Every entry, placed on each day it spans (start through end inclusive). */
export function buildEntriesByDate(entries: CalendarEntry[]): Map<string, CalendarEntry[]> {
  const map = new Map<string, CalendarEntry[]>();
  for (const entry of entries) {
    const { start, end } = parseEntry(entry);
    if (Number.isNaN(start.getTime())) continue;

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

export type SpanPlacement = {
  entry: CalendarEntry;
  startCol: number; // 0-based column within the week row
  spanCols: number; // how many columns to span
  lane: number; // vertical slot index (for stacking)
  showTitle: boolean; // only show title on first visible day of span
};

/** Lane a set of span placements by their columns; returns the lane count. */
export const laneSpans = (spans: SpanPlacement[]): number =>
  assignLanes(
    spans,
    (s) => s.startCol,
    (s) => s.startCol + s.spanCols
  );

/**
 * For a week row (7 days), compute which entries span multiple days and
 * assign them lanes so they don't overlap visually.
 */
export function computeSpanPlacements(
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

    if (entryEnd <= entryStart) {
      // Single-day entry — collect for per-cell rendering
      const key = dateKey(start);
      if (weekDays.some((d) => dateKey(d) === key)) {
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

  return { spans, singleDay, maxLane: laneSpans(spans) };
}

// ---------------------------------------------------------------------------
// Drag-and-drop primitives
// ---------------------------------------------------------------------------

/** Identifies what a droppable target represents. ``day`` (month/week) moves
 *  the date and keeps the time; ``hour`` (day view) moves the time. */
export type DropData =
  | { type: "day"; dateKey: string }
  | { type: "hour"; hour: number; dateKey: string };

/**
 * An entry rendered as a ``<button>`` that doubles as a dnd-kit draggable.
 * When ``enabled`` is false it behaves exactly like a plain button (click to
 * select), so non-reschedulable calendars are unaffected.
 */
export function DraggableEntryButton({
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
      {entry.unread ? <UnreadDot className="ml-auto self-center ring-1 ring-background" /> : null}
    </button>
  );
}

/**
 * A ``<div>`` that doubles as a dnd-kit droppable while still forwarding the
 * slot's own click/keyboard handlers (used for ``onSlotClick``). Highlights on
 * hover-over during a drag.
 */
export function DroppableDiv({
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

// ---------------------------------------------------------------------------
// Time grid (day + week views)
// ---------------------------------------------------------------------------

/** The hour labels down the side of a time grid. */
export function HourGutter({ className }: { className: string }) {
  return (
    <div>
      {HOURS.map((hour) => (
        <div
          key={hour}
          className={cn(
            "flex items-start justify-end border-b pt-1 text-[10px] text-muted-foreground",
            className
          )}
          style={{ height: ROW_HEIGHT }}
        >
          {formatHourLabel(hour)}
        </div>
      ))}
    </div>
  );
}

/**
 * One day's column of a time grid: an hour slot per row — clickable, and a
 * drop target that moves an entry to this day and hour — with that day's slice
 * of every timed entry positioned over it, overlaps side by side.
 */
export function DayColumn({
  day,
  entries,
  onEntryClick,
  onSlotClick,
  dndEnabled = false,
  compact = false,
}: {
  day: Date;
  /** Timed entries; those not touching `day` are left out. */
  entries: CalendarEntry[];
  onEntryClick?: (entry: CalendarEntry) => void;
  onSlotClick?: (date: Date) => void;
  dndEnabled?: boolean;
  /** The narrower week column: tighter padding, times only on taller blocks. */
  compact?: boolean;
}) {
  const key = dateKey(day);
  const blocks: { entry: CalendarEntry; startHour: number; endHour: number; lane: number }[] = [];
  for (const entry of entries) {
    const seg = daySegmentHours(day, entry);
    if (seg) blocks.push({ entry, ...seg, lane: 0 });
  }
  const laneCount = Math.max(
    assignLanes(
      blocks,
      (b) => b.startHour,
      (b) => b.endHour
    ),
    1
  );

  const clickSlot = (hour: number) => {
    const slotDate = new Date(day);
    slotDate.setHours(hour, 0, 0, 0);
    onSlotClick?.(slotDate);
  };

  return (
    <div className="relative border-l">
      {HOURS.map((hour) => (
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
          onClick={() => clickSlot(hour)}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === " ") {
              e.preventDefault();
              clickSlot(hour);
            }
          }}
        />
      ))}

      {blocks.map((block) => {
        const height = Math.max((block.endHour - block.startHour) * ROW_HEIGHT, 20);
        const { start, end } = parseEntry(block.entry);
        return (
          // A multi-day timed event renders one block per day, so the dnd-kit
          // id carries the day to stay unique (data.entry is unchanged, so
          // reschedule routing is identical).
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
              top: block.startHour * ROW_HEIGHT,
              height,
              left: `calc(${(block.lane / laneCount) * 100}% + 2px)`,
              width: `calc(${100 / laneCount}% - 4px)`,
              borderLeft: `3px solid ${block.entry.color || "var(--primary)"}`,
              backgroundColor: "var(--card)",
              boxShadow: "0 1px 3px rgba(0,0,0,0.1)",
            }}
          >
            <div className={cn("flex flex-col", compact ? "px-1.5 py-0.5" : "px-2 py-1")}>
              <span className="truncate font-medium">{block.entry.title}</span>
              {!compact || height >= 32 ? (
                <span className="text-[10px] text-muted-foreground">
                  {formatTime(start)} – {formatTime(end)}
                </span>
              ) : null}
            </div>
          </DraggableEntryButton>
        );
      })}
    </div>
  );
}
