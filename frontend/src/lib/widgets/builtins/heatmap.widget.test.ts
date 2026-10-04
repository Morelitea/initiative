/**
 * What a heatmap says when it draws nothing.
 *
 * It has two ways of drawing nothing and they are not the same news. "No date
 * column" is about the query — the author pointed the tile at columns this
 * widget cannot place on a calendar, and they have to change something.
 * "Nothing recorded yet" is about the data: the query is right and the answer
 * is that nobody has done the thing yet. A tile that reports the first when it
 * means the second sends its reader to fix a query that was never wrong.
 */
import { describe, expect, it } from "vitest";

import type { TabularData } from "../dataShapes";
import { builtinWidgetSource } from "../registry";
import { renderInSandbox } from "../runtime/sandbox";
import { validateScene } from "../validateScene";

const AT_AND_VALUE = { at: [0], value: [1] };

const draw = async (data: TabularData, slots: Record<string, number[]> = AT_AND_VALUE) => {
  const result = await renderInSandbox({
    source: builtinWidgetSource("heatmap") as string,
    data,
    config: {},
    slots,
  });
  expect(result.ok, JSON.stringify(result)).toBe(true);
  if (!result.ok) throw new Error("render failed");
  const validation = validateScene(result.value);
  expect(validation.ok, JSON.stringify(validation)).toBe(true);
  if (!validation.ok) throw new Error("invalid scene");
  return validation.spec.scene;
};

const table = (rows: TabularData["rows"]): TabularData => ({
  source: "rows",
  columns: [
    { name: "day", type: "date" },
    { name: "tasks", type: "number" },
  ],
  rows,
});

describe("a heatmap with nothing to draw", () => {
  it("says nothing is recorded when the query answered with no rows", async () => {
    // A completion heatmap over an initiative where nothing is finished yet.
    const scene = await draw(table([]));
    expect(JSON.stringify(scene)).toContain("Nothing recorded");
  });

  it("says which column is missing when it has no date to place values on", async () => {
    const scene = await draw(table([[1757376000000, 3]]), { value: [1] });
    expect(JSON.stringify(scene)).toContain("No date column");
  });

  it("says so too when rows carry no readable date", async () => {
    const scene = await draw(table([["not a day", 3]]));
    expect(JSON.stringify(scene)).toContain("No date column");
  });

  it("draws the days it was given", async () => {
    const scene = await draw(table([[1757376000000, 3]]));
    expect(JSON.stringify(scene)).not.toContain("No date column");
    expect(JSON.stringify(scene)).not.toContain("Nothing recorded");
  });
});

describe("a heatmap of dates grouped coarser than a day", () => {
  const at = (iso: string) => Date.parse(`${iso}T00:00:00Z`);
  const rounded = (grain: string, rows: TabularData["rows"]): TabularData => ({
    source: "rows",
    columns: [
      { name: "day", type: "date", grain } as TabularData["columns"][number],
      { name: "tasks", type: "number" },
    ],
    rows,
  });

  it("draws months as a row per year", async () => {
    const scene = await draw(
      rounded("month", [
        [at("2026-01-01"), 3],
        [at("2026-04-01"), 5],
        [at("2027-03-01"), 1],
      ])
    );
    if (scene.kind !== "matrix") throw new Error("not a matrix");
    expect(scene.yLabels).toEqual(["2026", "2027"]);
    expect(scene.xLabels).toHaveLength(12);
    expect(scene.cells.map((cell) => [cell.x, cell.y, cell.value])).toEqual([
      [0, 0, 3],
      [3, 0, 5],
      [2, 1, 1],
    ]);
    expect(scene.cells[0].label).toBe("Jan 2026: 3");
  });

  it("draws weeks as one strip, a column each", async () => {
    const scene = await draw(
      rounded("week", [
        [at("2026-09-07"), 2],
        [at("2026-09-21"), 4],
        [at("2026-09-28"), 1],
      ])
    );
    if (scene.kind !== "matrix") throw new Error("not a matrix");
    expect(scene.yLabels).toHaveLength(1);
    expect(scene.cells.map((cell) => cell.x)).toEqual([0, 2, 3]);
    expect(scene.cells[0].label).toBe("Week of 2026-09-07: 2");
  });

  it("names quarters in the reader's language", async () => {
    const result = await renderInSandbox({
      source: builtinWidgetSource("heatmap") as string,
      data: rounded("quarter", [[at("2026-04-01"), 2]]),
      config: {},
      slots: AT_AND_VALUE,
      locale: "fr",
    });
    if (!result.ok) throw new Error("render failed");
    const validation = validateScene(result.value);
    if (!validation.ok || validation.spec.scene.kind !== "matrix") throw new Error("invalid");
    expect(validation.spec.scene.xLabels).toEqual(["T1", "T2", "T3", "T4"]);
  });

  it("draws years along one row", async () => {
    const scene = await draw(
      rounded("year", [
        [at("2024-01-01"), 2],
        [at("2026-01-01"), 4],
      ])
    );
    if (scene.kind !== "matrix") throw new Error("not a matrix");
    expect(scene.xLabels).toEqual(["2024", "2025", "2026"]);
  });

  it("draws a plain date on the day calendar", async () => {
    const scene = await draw(
      table([
        [at("2026-01-01"), 1],
        [at("2026-04-01"), 1],
      ])
    );
    if (scene.kind !== "matrix") throw new Error("not a matrix");
    expect(scene.yLabels).toHaveLength(7);
  });
});
