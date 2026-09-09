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
