/**
 * The chart through the whole path it takes in production: sandboxed module,
 * validator, scene.
 *
 * What is worth pinning here is the arrangement — the order categories end up
 * in, and what happens to the ones past the cap. Those are decisions the widget
 * makes over its data, invisible in a rendering, and the multi-series case is
 * where getting them wrong produces a chart that is quietly wrong rather than
 * obviously broken.
 */
import { describe, expect, it } from "vitest";

import type { ProjectRow, WidgetData } from "../dataShapes";
import { builtinWidgetSource } from "../registry";
import { renderInSandbox } from "../runtime/sandbox";
import type { SeriesNode } from "../sceneSpec";
import { validateScene } from "../validateScene";

const draw = async (
  data: WidgetData,
  config: Record<string, string> = {},
  locale?: string
): Promise<SeriesNode> => {
  const result = await renderInSandbox({
    source: builtinWidgetSource("chart") as string,
    data,
    config,
    locale,
  });
  expect(result.ok, JSON.stringify(result)).toBe(true);
  if (!result.ok) throw new Error("render failed");

  const validation = validateScene(result.value);
  expect(validation.ok, JSON.stringify(validation)).toBe(true);
  if (!validation.ok) throw new Error("invalid scene");
  return validation.spec.scene as SeriesNode;
};

const project = (name: string, taskCount: number, doneCount: number): ProjectRow => ({
  id: name.length,
  name,
  startDate: null,
  endDate: null,
  progress: taskCount ? doneCount / taskCount : 0,
  taskCount,
  doneCount,
  ownerName: null,
  tags: [],
});

/** Six projects, so a limit of 5 leaves exactly one in the tail. */
const projects: WidgetData = {
  source: "projects",
  rows: [
    project("Apollo", 10, 8),
    project("Boreas", 9, 6),
    project("Cronos", 8, 5),
    project("Delos", 7, 4),
    project("Eos", 6, 3),
    project("Fates", 5, 1),
  ],
  tasks: [],
};

const counts = (buckets: [string, number][]): WidgetData => ({
  source: "task_counts",
  rows: buckets.map(([bucket, count]) => ({ bucket, count })),
});

describe("ordering", () => {
  it("keeps the source's own order by default", async () => {
    const scene = await draw(
      counts([
        ["c", 1],
        ["a", 9],
        ["b", 5],
      ])
    );
    expect(scene.series[0].points.map((point) => point.x)).toEqual(["c", "a", "b"]);
  });

  it("sorts by value when asked", async () => {
    const scene = await draw(
      counts([
        ["c", 1],
        ["a", 9],
        ["b", 5],
      ]),
      { sort: "value_desc" }
    );
    expect(scene.series[0].points.map((point) => point.x)).toEqual(["a", "b", "c"]);
  });

  it("puts the largest slice first for a pie whatever the order says", async () => {
    const scene = await draw(
      counts([
        ["c", 1],
        ["a", 9],
      ]),
      { mark: "pie", sort: "source" }
    );
    expect(scene.series[0].points.map((point) => point.x)).toEqual(["a", "c"]);
  });
});

describe("the category cap", () => {
  it("draws every category when under the cap", async () => {
    const scene = await draw(projects, { limit: "12" });
    expect(scene.series[0].points).toHaveLength(6);
    expect(scene.series[0].points.some((point) => point.x === "Other")).toBe(false);
  });

  it("folds the tail into one category rather than drawing more colours", async () => {
    const scene = await draw(projects, { limit: "5" });
    expect(scene.series[0].points).toHaveLength(6);
    expect(scene.series[0].points.at(-1)?.x).toBe("Other");
  });

  it("gives every series its own share of the folded tail", async () => {
    // The failure this pins: folding one series and rebuilding the other from
    // raw rows leaves "Other" with a value on one side and nothing on the
    // other, so the bar under-reports and the two series stop summing to the
    // real total.
    const scene = await draw(projects, { limit: "5" });
    const [done, remaining] = scene.series;

    const other = (series: (typeof scene.series)[number]) =>
      series.points.find((point) => point.x === "Other");

    expect(other(done)?.y).toBe(1);
    expect(other(remaining)?.y).toBe(4);
  });

  it("keeps both series on one shared category order", async () => {
    const scene = await draw(projects, { limit: "5", sort: "value_asc" });
    const [done, remaining] = scene.series;
    expect(done.points.map((point) => point.x)).toEqual(remaining.points.map((point) => point.x));
  });

  it("totals every series when deciding which categories survive", async () => {
    // Fates is last on "Done" alone but not on the total, and the cut is made
    // on the total — otherwise the two series would disagree about who stayed.
    const scene = await draw(projects, { limit: "5" });
    const kept = scene.series[0].points.map((point) => point.x);
    expect(kept).toContain("Apollo");
    expect(kept).not.toContain("Fates");
  });
});

describe("a category that shares the fold's name", () => {
  /** The biggest project by far, and called exactly what the fold is called. */
  const withOther: WidgetData = {
    source: "projects",
    rows: [
      project("Other", 100, 90),
      project("Boreas", 9, 6),
      project("Cronos", 8, 5),
      project("Delos", 7, 4),
      project("Eos", 6, 3),
      project("Fates", 5, 1),
    ],
    tasks: [],
  };

  it("draws one bar for it, not two", async () => {
    // Two points sharing an x do not draw as two bars: the renderer merges on
    // x, so one silently replaces the other and its value leaves the chart.
    const scene = await draw(withOther, { limit: "5" });
    const others = scene.series[0].points.filter((point) => point.x === "Other");
    expect(others).toHaveLength(1);
  });

  it("still counts everything it folded", async () => {
    const scene = await draw(withOther, { limit: "5" });
    const [done, remaining] = scene.series;
    const other = (series: (typeof scene.series)[number]) =>
      series.points.find((point) => point.x === "Other");

    // The real "Other" project (90 done, 10 outstanding) plus Fates (1, 4).
    expect(other(done)?.y).toBe(91);
    expect(other(remaining)?.y).toBe(14);
  });

  it("keeps the chart's totals equal to the source's", async () => {
    const scene = await draw(withOther, { limit: "5" });
    const sum = (index: number) =>
      scene.series[index].points.reduce((total, point) => total + point.y, 0);
    expect(sum(0)).toBe(90 + 6 + 5 + 4 + 3 + 1);
    expect(sum(1)).toBe(10 + 3 + 3 + 3 + 3 + 4);
  });

  it("leaves it alone when nothing is being folded", async () => {
    const scene = await draw(withOther, { limit: "all" });
    expect(scene.series[0].points.map((point) => point.x)).toContain("Other");
    expect(scene.series[0].points.filter((point) => point.x === "Other")).toHaveLength(1);
    expect(scene.series[0].points.find((point) => point.x === "Other")?.y).toBe(90);
  });
});

describe("emphasis", () => {
  it("names no series when the scene asks for none", async () => {
    const scene = await draw(projects, { emphasis: "none" });
    expect(scene.emphasis).toBeUndefined();
  });

  it("names the largest series so the renderer can gray the rest", async () => {
    const scene = await draw(projects, { emphasis: "largest" });
    expect(scene.emphasis).toBe(0);
  });
});

describe("the widget's own words", () => {
  it("speaks the language the host hands it", async () => {
    const scene = await draw(projects, { limit: "5" }, "de");
    expect(scene.series[0].name).toBe("Erledigt");
    expect(scene.series[0].points.at(-1)?.x).toBe("Sonstige");
  });

  it("falls back to the base language for a regional tag", async () => {
    const scene = await draw(projects, {}, "fr-CA");
    expect(scene.series[0].name).toBe("Terminé");
  });

  it("falls back to English for a language it does not speak", async () => {
    const scene = await draw(projects, {}, "ja");
    expect(scene.series[0].name).toBe("Done");
  });
});
