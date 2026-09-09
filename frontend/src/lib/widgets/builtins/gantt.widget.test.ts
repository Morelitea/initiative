/**
 * The Gantt through the whole path it takes in production: sandboxed module,
 * validator, scene. Asserted on the scene rather than on the DOM, because the
 * decisions worth pinning here are the widget's — what becomes a group, what
 * becomes a milestone rather than a bar, what a total row is counting — and
 * none of them are visible in a rendering.
 */
import { describe, expect, it } from "vitest";

import type { CellValue, TabularData } from "../dataShapes";
import { builtinWidgetSource } from "../registry";
import { renderInSandbox } from "../runtime/sandbox";
import { SAMPLE_NOW } from "../sampleData";
import type { TimelineLane, TimelineNode } from "../sceneSpec";
import { validateScene } from "../validateScene";

const DAY = 86_400_000;
const T0 = SAMPLE_NOW;

const SLOTS = { label: [0], start: [1], end: [2], group: [3] };

const rows = (body: CellValue[][]): TabularData => ({
  source: "rows",
  columns: [
    { name: "task", type: "text" },
    { name: "starts", type: "date" },
    { name: "ends", type: "date" },
    { name: "team", type: "text" },
  ],
  rows: body,
});

const draw = async (
  data: TabularData,
  config: Record<string, string> = {},
  slots: Record<string, number[]> = SLOTS
): Promise<TimelineNode> => {
  const result = await renderInSandbox({
    source: builtinWidgetSource("gantt") as string,
    data,
    config,
    slots,
    now: T0,
  });
  expect(result.ok, JSON.stringify(result)).toBe(true);
  if (!result.ok) throw new Error("render failed");

  // Through the same boundary a live tile crosses, so a field the validator
  // would drop cannot be asserted on here either.
  const validation = validateScene(result.value);
  expect(validation.ok, JSON.stringify(validation)).toBe(true);
  if (!validation.ok) throw new Error("invalid scene");
  expect(validation.spec.scene.kind).toBe("timeline");
  return validation.spec.scene as TimelineNode;
};

const laneNamed = (lanes: TimelineLane[], label: string): TimelineLane => {
  const found = lanes.find((lane) => lane.label === label);
  if (!found) throw new Error(`no lane ${label} in ${lanes.map((l) => l.label).join(", ")}`);
  return found;
};

const work = rows([
  ["Design review", T0 - 12 * DAY, T0 - 5 * DAY, "Platform"],
  ["Build the importer", T0 - 6 * DAY, T0 + 4 * DAY, "Platform"],
  ["Write the migration", T0 - 2 * DAY, T0 + 9 * DAY, "Data"],
]);

describe("lanes", () => {
  it("folds rows into the column mapped to the group slot", async () => {
    const scene = await draw(work);
    const platform = laneNamed(scene.lanes, "Platform");
    expect(platform.children?.map((lane) => lane.label).sort()).toEqual([
      "Build the importer",
      "Design review",
    ]);
    expect(laneNamed(scene.lanes, "Data").children).toHaveLength(1);
  });

  it("draws every row flat when grouping is off", async () => {
    const scene = await draw(work, { group: "none", rollup: "off" });
    expect(scene.lanes.map((lane) => lane.label).sort()).toEqual([
      "Build the importer",
      "Design review",
      "Write the migration",
    ]);
  });

  it("puts a total row above everything", async () => {
    const scene = await draw(work, { rollup: "on" });
    expect(scene.lanes[0].label).toBe("Everything");
    // Two of the three have already ended.
    expect(scene.lanes[0].caption).toBe("1/3");
  });
});

describe("spans", () => {
  it("draws a row with a start and an end as a bar", async () => {
    const scene = await draw(work, { group: "none", rollup: "off" });
    const lane = laneNamed(scene.lanes, "Design review");
    expect(lane.spans[0].kind).toBe("bar");
    expect(lane.spans[0].start).toBe(T0 - 12 * DAY);
  });

  it("draws a row with only an end as a dated instant", async () => {
    // A date with nothing before it is a moment, not a stretch of work.
    const milestone = rows([["Ship it", null, T0 + 3 * DAY, "Platform"]]);
    const scene = await draw(milestone, { group: "none", rollup: "off" });
    expect(laneNamed(scene.lanes, "Ship it").spans[0].kind).toBe("milestone");
  });

  it("leaves out a row with no dates at all", async () => {
    // It has nowhere to sit on an axis, and a zero-width bar at an arbitrary
    // point would be a lie rather than a gap. With nothing else to draw the
    // widget says so rather than showing an axis over an empty chart.
    const undated = rows([["Someday", null, null, "Platform"]]);
    const result = await renderInSandbox({
      source: builtinWidgetSource("gantt") as string,
      data: undated,
      config: { group: "none", rollup: "off" },
      slots: SLOTS,
      now: T0,
    });
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    const validation = validateScene(result.value);
    expect(validation.ok).toBe(true);
    if (!validation.ok) return;
    expect(validation.spec.scene.kind).toBe("empty");
  });

  it("tones work whose end has passed as done with", async () => {
    const scene = await draw(work, { group: "none", rollup: "off" });
    expect(laneNamed(scene.lanes, "Design review").spans[0].tone).toBe("muted");
    expect(laneNamed(scene.lanes, "Build the importer").spans[0].tone).toBe("accent");
  });
});

describe("what it refuses to draw", () => {
  it("says so when no date column was mapped", async () => {
    const result = await renderInSandbox({
      source: builtinWidgetSource("gantt") as string,
      data: work,
      config: {},
      slots: { label: [0] },
      now: T0,
    });
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    const validation = validateScene(result.value);
    expect(validation.ok).toBe(true);
    if (!validation.ok) return;
    expect(validation.spec.scene.kind).toBe("empty");
  });
});
