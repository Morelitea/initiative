import { useCallback, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { cn } from "@/lib/utils";

/**
 * One stop on the rail.
 *
 * Deliberately not any tool's own shape. A month with things in it and a place
 * to land is the whole vocabulary — a board's notices, a calendar's events and
 * a project's activity would each hand back this same list, so the rail is
 * written once and each tool adapts its own response into it.
 */
export interface TimelineStop {
  /** Stable identity, and what an active stop is compared by. `YYYY-MM`. */
  period: string;
  /** How many rows fall in it — what gives the rail its density. */
  count: number;
}

interface TimelineRailProps<T extends TimelineStop> {
  stops: T[];
  /** The `period` currently at the top of the view, marked on the rail. */
  activePeriod?: string | null;
  onPick: (stop: T) => void;
  /** Localized label for a stop, e.g. "March 2026". Kept out of the rail so it
   *  formats in the caller's own locale and vocabulary. */
  formatLabel: (stop: T) => string;
  /** Short label drawn beside a tick where the year changes, e.g. "2026". */
  formatGroup: (stop: T) => string;
  className?: string;
}

/** The tallest a tick gets relative to the rail, and the shortest. A month
 *  with one row still has to be a target somebody can hit. */
const MIN_TICK = 0.35;

/** How wide the rail's hit area is. The visible ticks are narrower; this is
 *  what a finger actually lands on, and it is the reason the rail is usable on
 *  a phone rather than a desktop-only affordance.
 *
 *  Wide enough for a year to sit INSIDE it. A label placed outside the rail —
 *  `right-full`, say — hangs over whatever the rail is beside, which on a feed
 *  is the content somebody is reading. */
const RAIL_HIT_WIDTH = "w-11";

/**
 * A draggable rail of periods, for jumping a long feed to a date.
 *
 * The photo-library pattern: months as ticks down the edge, years labelled,
 * and a bubble that follows a finger or a cursor naming the month under it.
 * One control that behaves the same on a phone and a desktop rather than a
 * hover affordance with a separate mobile substitute.
 *
 * Each stop is a real `<button>`, so the rail is a list somebody can tab
 * through and a screen reader can read, and the dragging is layered on top of
 * that rather than replacing it. `touch-action: none` on the rail is what
 * stops a drag scrolling the page underneath it.
 *
 * Density is drawn, not counted: a tick's length is its share of the busiest
 * month, which is what makes a year of quiet months and one loud one legible
 * at a glance.
 */
export function TimelineRail<T extends TimelineStop>({
  stops,
  activePeriod,
  onPick,
  formatLabel,
  formatGroup,
  className,
}: TimelineRailProps<T>) {
  const { t } = useTranslation("common");
  const railRef = useRef<HTMLDivElement | null>(null);
  // The stop under the finger mid-drag, and where on the rail the finger is.
  // Separate from `activePeriod`, which is where the feed actually is: during a
  // drag the bubble runs ahead of it.
  const [dragging, setDragging] = useState<{ stop: T; offset: number; moved: boolean } | null>(
    null
  );

  const busiest = useMemo(
    () => stops.reduce((most, stop) => Math.max(most, stop.count), 1),
    [stops]
  );

  /** The stop under a pointer at this y, clamped to the ends so a drag that
   *  runs off the rail keeps tracking rather than going dead. */
  const stopAt = useCallback(
    (clientY: number): T | null => {
      const rail = railRef.current;
      if (!rail || stops.length === 0) return null;
      const box = rail.getBoundingClientRect();
      const ratio = (clientY - box.top) / Math.max(box.height, 1);
      const index = Math.round(ratio * (stops.length - 1));
      return stops[Math.min(Math.max(index, 0), stops.length - 1)] ?? null;
    },
    [stops]
  );

  const track = useCallback(
    (event: React.PointerEvent, moved: boolean) => {
      const rail = railRef.current;
      const stop = stopAt(event.clientY);
      if (!rail || !stop) return;
      const box = rail.getBoundingClientRect();
      // Clamped to the rail, so a drag that runs off the end leaves the bubble
      // at the end rather than sliding away up the page with the finger.
      const offset = Math.min(Math.max(event.clientY - box.top, 0), box.height);
      setDragging((current) => ({ stop, offset, moved: moved || (current?.moved ?? false) }));
    },
    [stopAt]
  );

  if (stops.length === 0) return null;

  return (
    <div
      ref={railRef}
      // `touch-action: none` so a drag down the rail scrubs it rather than
      // scrolling the feed behind it.
      className={cn(
        "relative flex shrink-0 touch-none select-none flex-col justify-between py-1",
        RAIL_HIT_WIDTH,
        className
      )}
      aria-label={t("timeline.label")}
      onPointerDown={(event) => {
        // Capture, so the drag keeps tracking once the finger leaves the rail.
        event.currentTarget.setPointerCapture(event.pointerId);
        track(event, false);
      }}
      onPointerMove={(event) => {
        if (dragging) track(event, true);
      }}
      onPointerUp={(event) => {
        const stop = stopAt(event.clientY);
        // A press that never moved is a click, and the stop under it is a real
        // button whose own handler is about to fire — picking here as well
        // would run the caller's callback twice for one activation. A press on
        // the rail's own space has no button to fall through to, so it is
        // picked here.
        const wasDrag = dragging?.moved ?? false;
        const onButton = (event.target as Element | null)?.closest("button") != null;
        setDragging(null);
        if (stop && (wasDrag || !onButton)) onPick(stop);
      }}
      onPointerCancel={() => setDragging(null)}
    >
      {stops.map((stop, index) => {
        const isActive = stop.period === activePeriod;
        const isUnderFinger = dragging?.stop.period === stop.period;
        // A year label where the year changes, and on the first stop, so the
        // top of the rail always says what it is showing. It sits in the flow
        // above its first tick rather than beside the rail — anything placed
        // outside the rail's own width lands on top of the feed it is next to.
        const group = formatGroup(stop);
        const startsGroup = index === 0 || formatGroup(stops[index - 1]) !== group;
        return (
          <div key={stop.period} className="flex flex-col items-end gap-0.5">
            {startsGroup && (
              <span
                aria-hidden
                className="pointer-events-none pr-0.5 text-[0.625rem] text-muted-foreground leading-none tabular-nums"
              >
                {group}
              </span>
            )}
            <button
              type="button"
              title={formatLabel(stop)}
              aria-label={formatLabel(stop)}
              aria-current={isActive ? "true" : undefined}
              onClick={() => onPick(stop)}
              className="group flex h-3 w-full items-center justify-end pr-0.5"
            >
              <span
                className={cn(
                  "h-0.5 rounded-full transition-colors",
                  isActive || isUnderFinger
                    ? "bg-primary"
                    : "bg-muted-foreground/30 group-hover:bg-muted-foreground/60"
                )}
                style={{
                  width: `${Math.round((MIN_TICK + (1 - MIN_TICK) * (stop.count / busiest)) * 100)}%`,
                }}
              />
            </button>
          </div>
        );
      })}

      {/* The bubble, naming the month under the finger. Only while dragging:
          a label that is always there is a legend, not a readout. */}
      {dragging && (
        <span
          role="status"
          style={{ top: dragging.offset }}
          className="pointer-events-none absolute right-full z-20 mr-2 -translate-y-1/2 whitespace-nowrap rounded-md border bg-popover px-2 py-1 font-medium text-popover-foreground text-xs shadow-md"
        >
          {formatLabel(dragging.stop)}
        </span>
      )}
    </div>
  );
}
