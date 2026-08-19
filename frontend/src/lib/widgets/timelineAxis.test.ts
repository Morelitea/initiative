/**
 * The axis is the part of a Gantt that is wrong silently: a tick a day off, a
 * window that starts mid-week, a weekend stripe on a Tuesday — all of them look
 * fine in a screenshot. So the arithmetic is asserted directly.
 *
 * Every date here is built with local-time constructors, because the module is
 * local-time by design (it runs in the viewer's zone, which the widget did not
 * have). That keeps the expectations true whatever zone the suite runs in.
 */
import { describe, expect, it } from "vitest";

import type { TimelineLane, TimelineNode } from "./sceneSpec";
import {
  addUnits,
  axisTicks,
  flattenLanes,
  floorToUnit,
  majorSegments,
  positionIn,
  timelineWindow,
  weekendBands,
} from "./timelineAxis";

const at = (year: number, month: number, day: number, hour = 0): number =>
  new Date(year, month, day, hour).getTime();

// 3 August 2026 is a Monday.
const MONDAY = at(2026, 7, 3);

const lane = (spans: TimelineLane["spans"], extra: Partial<TimelineLane> = {}): TimelineLane => ({
  spans,
  ...extra,
});

const node = (lanes: TimelineLane[], extra: Partial<TimelineNode> = {}): TimelineNode => ({
  kind: "timeline",
  lanes,
  ...extra,
});

describe("floorToUnit", () => {
  it("floors to the start of the day, discarding the time", () => {
    expect(floorToUnit(at(2026, 7, 3, 17), "day")).toBe(at(2026, 7, 3));
  });

  it("floors to the week the locale starts on", () => {
    // Sunday-first puts Monday the 3rd in the week beginning the 2nd; Monday-
    // first leaves it at the start of its own week.
    expect(floorToUnit(MONDAY, "week", 0)).toBe(at(2026, 7, 2));
    expect(floorToUnit(MONDAY, "week", 1)).toBe(MONDAY);
  });

  it("floors to the month and to the quarter containing it", () => {
    expect(floorToUnit(MONDAY, "month")).toBe(at(2026, 7, 1));
    expect(floorToUnit(MONDAY, "quarter")).toBe(at(2026, 6, 1));
  });
});

describe("addUnits", () => {
  it("steps by the calendar, not by a fixed number of milliseconds", () => {
    // Every month boundary of an ordinary year, including the short one and the
    // wrap into the next — a fixed 30-day step lands on none of them.
    let month = at(2026, 0, 1);
    for (let index = 1; index <= 12; index++) {
      month = addUnits(month, "month", 1);
      expect(month).toBe(at(2026 + Math.floor(index / 12), index % 12, 1));
    }
    expect(addUnits(at(2026, 6, 1), "quarter", 1)).toBe(at(2026, 9, 1));
    expect(addUnits(at(2026, 9, 1), "quarter", 1)).toBe(at(2027, 0, 1));
  });

  it("keeps a day step landing on the next midnight", () => {
    // True across a daylight-saving boundary, where a day is 23 or 25 hours.
    for (let day = 1; day <= 28; day++) {
      const next = new Date(addUnits(at(2026, 2, day), "day", 1));
      expect(next.getHours()).toBe(0);
      expect(next.getDate()).toBe(day + 1);
    }
  });
});

describe("timelineWindow", () => {
  it("takes an explicit window from the widget as given", () => {
    const window = timelineWindow(
      node([lane([{ start: MONDAY, end: MONDAY + 86_400_000 }])], {
        start: at(2026, 0, 1),
        end: at(2026, 11, 31),
      })
    );
    expect(window).toEqual({ start: at(2026, 0, 1), end: at(2026, 11, 31) });
  });

  it("fits the spans and snaps out to whole units", () => {
    const window = timelineWindow(
      node([lane([{ start: at(2026, 7, 5, 9), end: at(2026, 7, 12, 17) }])], { scale: "week" }),
      1
    );
    // Monday before the first span, Monday after the last.
    expect(window.start).toBe(at(2026, 7, 3));
    expect(window.end).toBe(at(2026, 7, 17));
  });

  it("counts a baseline as part of what has to fit", () => {
    const window = timelineWindow(
      node(
        [
          lane([
            {
              start: at(2026, 7, 10),
              end: at(2026, 7, 12),
              baseline: { start: at(2026, 7, 3), end: at(2026, 7, 5) },
            },
          ]),
        ],
        { scale: "day" }
      )
    );
    expect(window.start).toBe(at(2026, 7, 3));
  });

  it("reaches into folded children, which are still part of the schedule", () => {
    const window = timelineWindow(
      node(
        [
          lane([{ start: at(2026, 7, 10), end: at(2026, 7, 11) }], {
            collapsed: true,
            children: [lane([{ start: at(2026, 7, 4), end: at(2026, 7, 20) }])],
          }),
        ],
        { scale: "day" }
      )
    );
    expect(window.start).toBe(at(2026, 7, 4));
    expect(window.end).toBe(at(2026, 7, 21));
  });

  it("gives a window with width even when nothing is dated", () => {
    const window = timelineWindow(node([lane([])]));
    expect(window.end).toBeGreaterThan(window.start);
  });
});

describe("axisTicks", () => {
  it("puts every tick on a real unit boundary", () => {
    const range = { start: at(2026, 7, 3), end: at(2026, 7, 31) };
    for (const tick of axisTicks(range, "week", 1)) {
      expect(new Date(tick.at).getDay()).toBe(1);
      expect(new Date(tick.at).getHours()).toBe(0);
    }
  });

  it("widens the step rather than drawing a tick per unit", () => {
    // Three years asked for in days: over a thousand columns if the hint were
    // taken literally.
    const ticks = axisTicks({ start: at(2026, 0, 1), end: at(2029, 0, 1) }, "day", 0, 12);
    expect(ticks.length).toBeLessThanOrEqual(24);
    expect(ticks.length).toBeGreaterThan(4);
  });

  it("keeps every tick inside the window", () => {
    const range = { start: at(2026, 7, 5), end: at(2026, 9, 5) };
    for (const tick of axisTicks(range, "month", 0)) {
      expect(tick.at).toBeGreaterThanOrEqual(range.start);
      expect(tick.at).toBeLessThan(range.end);
    }
  });
});

describe("majorSegments", () => {
  it("draws the coarser unit above the scale, clipped to the window", () => {
    const range = { start: at(2026, 7, 10), end: at(2026, 9, 10) };
    const { segments, unit } = majorSegments(range, "week", 1);
    expect(unit).toBe("month");
    expect(segments.map((segment) => segment.at)).toEqual([
      at(2026, 7, 1),
      at(2026, 8, 1),
      at(2026, 9, 1),
    ]);
    // The first and last are cut to the window; the middle one is whole.
    expect(segments[0].start).toBe(range.start);
    expect(segments[2].end).toBe(range.end);
    expect(segments[1].start).toBe(at(2026, 8, 1));
  });

  it("puts years above months and quarters", () => {
    expect(majorSegments({ start: at(2026, 0, 1), end: at(2026, 6, 1) }, "month").unit).toBe(
      "year"
    );
    expect(majorSegments({ start: at(2026, 0, 1), end: at(2027, 6, 1) }, "quarter").unit).toBe(
      "year"
    );
  });
});

describe("weekendBands", () => {
  it("paints Saturday and Sunday as one stripe", () => {
    const bands = weekendBands({ start: at(2026, 7, 3), end: at(2026, 7, 17) });
    expect(bands).toHaveLength(2);
    // 8 August 2026 is a Saturday; the band runs to Monday morning.
    expect(bands[0].start).toBe(at(2026, 7, 8));
    expect(bands[0].end).toBe(at(2026, 7, 10));
  });

  it("draws nothing once the stripes would outnumber what they mark", () => {
    expect(weekendBands({ start: at(2024, 0, 1), end: at(2027, 0, 1) })).toEqual([]);
  });
});

describe("flattenLanes", () => {
  const tree: TimelineLane[] = [
    lane([], {
      label: "Apollo",
      children: [lane([], { label: "Spec" }), lane([], { label: "Migration" })],
    }),
    lane([], { label: "Borealis", collapsed: true, children: [lane([], { label: "Copy" })] }),
  ];

  it("leaves out what a folded lane hides", () => {
    const rows = flattenLanes(tree, (_path, item) => !item.collapsed);
    expect(rows.map((row) => row.lane.label)).toEqual(["Apollo", "Spec", "Migration", "Borealis"]);
  });

  it("identifies a lane by position, since labels repeat", () => {
    const rows = flattenLanes(tree, () => true);
    expect(rows.map((row) => row.path)).toEqual(["0", "0.0", "0.1", "1", "1.0"]);
    expect(rows.map((row) => row.depth)).toEqual([0, 1, 1, 0, 1]);
  });

  it("numbers each row among its own siblings", () => {
    const rows = flattenLanes(tree, () => true);
    const child = rows.find((row) => row.path === "0.1");
    expect(child).toMatchObject({ position: 2, setSize: 2 });
    expect(rows[0]).toMatchObject({ position: 1, setSize: 2, hasChildren: true, expanded: true });
  });

  it("does not call a childless lane expandable, whatever the fold state says", () => {
    const rows = flattenLanes([lane([], { label: "Solo" })], () => true);
    expect(rows[0]).toMatchObject({ hasChildren: false, expanded: false });
  });
});

describe("positionIn", () => {
  it("maps the window onto a percentage", () => {
    const range = { start: 0, end: 100 };
    expect(positionIn(range, 0)).toBe(0);
    expect(positionIn(range, 50)).toBe(50);
    expect(positionIn(range, 100)).toBe(100);
  });

  it("lets a value outside the window fall outside the axis", () => {
    // Clamping is the renderer's call: a bar starting before the window should
    // be cut off at the edge, not moved onto it.
    expect(positionIn({ start: 0, end: 100 }, -50)).toBe(-50);
  });
});
