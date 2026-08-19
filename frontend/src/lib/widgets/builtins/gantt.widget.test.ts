/**
 * The Gantt through the whole path it takes in production: sandboxed module,
 * validator, scene. Asserted on the scene rather than on the DOM, because the
 * decisions worth pinning here are the widget's — what becomes a group, what
 * counts as done, what a total row is counting — and none of them are visible
 * in a rendering.
 */
import { describe, expect, it } from "vitest";

import type { WidgetSource } from "../dataShapes";
import { builtinWidgetSource } from "../registry";
import { renderInSandbox } from "../runtime/sandbox";
import { SAMPLE_NOW, sampleFor } from "../sampleData";
import type { TimelineLane, TimelineNode } from "../sceneSpec";
import { validateScene } from "../validateScene";

const draw = async (
  source: WidgetSource,
  config: Record<string, string> = {}
): Promise<TimelineNode> => {
  const result = await renderInSandbox({
    source: builtinWidgetSource("gantt") as string,
    data: sampleFor(source, "gantt"),
    config,
    now: SAMPLE_NOW,
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

const childNamed = (lane: TimelineLane, label: string): TimelineLane =>
  laneNamed(lane.children ?? [], label);

describe("gantt over projects", () => {
  it("makes each project a group its own work folds into", async () => {
    const scene = await draw("projects");
    const apollo = laneNamed(scene.lanes, "Apollo");

    expect(apollo.spans[0].kind).toBe("summary");
    // Two of Apollo's four tasks are done, and that is what the bracket fills to.
    expect(apollo.spans[0].progress).toBe(0.5);
    expect(apollo.caption).toBe("2/4");
    expect(apollo.children?.map((child) => child.label)).toContain("Migrate the search index");
  });

  it("counts projects, not tasks, in the total row", async () => {
    const scene = await draw("projects");
    // Cygnus is the only one of the three with all its work finished.
    expect(scene.lanes[0]).toMatchObject({ label: "All projects", caption: "1/3" });
    expect(scene.lanes[0].spans[0].progress).toBeCloseTo(1 / 3);
  });

  it("reaches across everything nested under it", async () => {
    const scene = await draw("projects");
    const total = scene.lanes[0].spans[0];
    const every = scene.lanes.slice(1).flatMap((lane) => lane.spans);
    expect(total.start).toBe(Math.min(...every.map((span) => span.start)));
    expect(total.end).toBe(Math.max(...every.map((span) => span.end)));
  });

  it("leaves the groups shut when the widget is set to start folded", async () => {
    const scene = await draw("projects", { start: "folded" });
    expect(laneNamed(scene.lanes, "Apollo").collapsed).toBe(true);
  });

  it("drops the total row when it is switched off", async () => {
    const scene = await draw("projects", { rollup: "off" });
    expect(scene.lanes.map((lane) => lane.label)).not.toContain("All projects");
  });

  it("stops nesting when grouping is off", async () => {
    const scene = await draw("projects", { group: "none" });
    for (const lane of scene.lanes) expect(lane.children ?? []).toHaveLength(0);
  });
});

describe("gantt over tasks", () => {
  it("groups by project by default, and by whatever else is asked for", async () => {
    expect((await draw("tasks")).lanes.map((lane) => lane.label)).toEqual(
      expect.arrayContaining(["Apollo", "Borealis", "No project"])
    );
    expect((await draw("tasks", { group: "assignee" })).lanes.map((lane) => lane.label)).toEqual(
      expect.arrayContaining(["Ada", "Grace", "Lin", "Unassigned"])
    );
  });

  it("puts shared work on every owner's row but counts it once", async () => {
    const scene = await draw("tasks", { group: "assignee" });
    // "Ship the migration" belongs to Grace and Ada, so it sits on both rows…
    expect(childNamed(laneNamed(scene.lanes, "Ada"), "Ship the migration")).toBeDefined();
    expect(childNamed(laneNamed(scene.lanes, "Grace"), "Ship the migration")).toBeDefined();
    // …while the total is still nine tasks, three of them done.
    expect(scene.lanes[0].caption).toBe("3/9");
  });

  it("draws a date with no duration as a milestone", async () => {
    const scene = await draw("tasks");
    // "Beta sign-off" has a due date and no start: an instant, not a stretch.
    const signOff = childNamed(laneNamed(scene.lanes, "Apollo"), "Beta sign-off");
    expect(signOff.spans[0].kind).toBe("milestone");
    expect(signOff.spans[0].start).toBe(signOff.spans[0].end);
  });

  it("keeps the plan as a baseline under work that did not land on it", async () => {
    const scene = await draw("tasks");
    const shipped = childNamed(laneNamed(scene.lanes, "Apollo"), "Ship the migration");
    const span = shipped.spans[0];
    expect(span.baseline).toBeDefined();
    // The bar runs to when it was actually finished; the ghost to when it was due.
    expect(span.end).toBeGreaterThan(span.baseline?.end ?? 0);
  });

  it("has no baseline for work that landed when it was planned to", async () => {
    const scene = await draw("tasks");
    expect(
      childNamed(laneNamed(scene.lanes, "Borealis"), "Rewrite the onboarding copy").spans[0]
        .baseline
    ).toBeUndefined();
  });

  it("tones work by whether it is done, late, or neither", async () => {
    const scene = await draw("tasks");
    const apollo = laneNamed(scene.lanes, "Apollo");
    expect(childNamed(apollo, "Draft the spec").spans[0].tone).toBe("positive");
    expect(childNamed(apollo, "Migrate the search index").spans[0].tone).toBe("accent");
    // Past its date and still open, which carries up to the group as well.
    const stalled = laneNamed(scene.lanes, "No project");
    expect(childNamed(stalled, "Chase the vendor").spans[0].tone).toBe("negative");
    expect(stalled.tone).toBe("negative");
  });

  it("gives one row per task when grouping is off", async () => {
    const scene = await draw("tasks", { group: "none" });
    expect(scene.lanes.map((lane) => lane.label)).toContain("Chase the vendor");
    for (const lane of scene.lanes) expect(lane.children ?? []).toHaveLength(0);
  });
});

describe("gantt over calendar entries", () => {
  it("groups by the calendar an entry sits on", async () => {
    const scene = await draw("calendar_entries");
    expect(laneNamed(scene.lanes, "Team").children?.map((child) => child.label)).toEqual([
      "Kickoff",
      "Retro",
    ]);
  });
});

describe("gantt scenes", () => {
  it("carries the minute it judged against, so the marker is not the renderer's own", async () => {
    expect((await draw("tasks")).now).toBe(SAMPLE_NOW);
  });

  it("passes the scale through as the axis hint", async () => {
    expect((await draw("tasks", { scale: "month" })).scale).toBe("month");
    expect((await draw("tasks")).scale).toBe("week");
  });
});
