/**
 * The board through the whole path it takes in production: sandboxed module,
 * validator, scene.
 *
 * What a board groups by is the column the author mapped, not a display option
 * — so the decisions worth pinning are what becomes a column, where the empty
 * bucket sits, and what a card carries beside its title.
 */
import { describe, expect, it } from "vitest";

import type { CellValue, TabularData } from "../dataShapes";
import { builtinWidgetSource } from "../registry";
import { renderInSandbox } from "../runtime/sandbox";
import { SAMPLE_NOW } from "../sampleData";
import type { BoardNode } from "../sceneSpec";
import { validateScene } from "../validateScene";

const DAY = 86_400_000;
const T0 = SAMPLE_NOW;
const SLOTS = { card: [0], column: [1], date: [2] };

const rows = (body: CellValue[][]): TabularData => ({
  source: "rows",
  columns: [
    { name: "task", type: "text" },
    { name: "status", type: "text" },
    { name: "due", type: "date" },
    { name: "owner", type: "text" },
  ],
  rows: body,
});

const draw = async (
  data: TabularData,
  config: Record<string, string> = {},
  slots: Record<string, number[]> = SLOTS
): Promise<BoardNode> => {
  const result = await renderInSandbox({
    source: builtinWidgetSource("board") as string,
    data,
    config,
    slots,
    now: T0,
  });
  expect(result.ok, JSON.stringify(result)).toBe(true);
  if (!result.ok) throw new Error("render failed");
  const validation = validateScene(result.value);
  expect(validation.ok, JSON.stringify(validation)).toBe(true);
  if (!validation.ok) throw new Error("invalid scene");
  expect(validation.spec.scene.kind).toBe("board");
  return validation.spec.scene as BoardNode;
};

const work = rows([
  ["Draft the brief", "Backlog", T0 + 3 * DAY, "Ada"],
  ["Wire the endpoint", "In progress", T0 - 1 * DAY, "Grace"],
  ["Review the copy", "In progress", T0 + 6 * DAY, "Ada"],
  ["Publish", "Done", T0 - 4 * DAY, "Grace"],
]);

describe("columns", () => {
  it("makes a column of each value in the mapped column", async () => {
    const scene = await draw(work);
    expect(scene.columns.map((column) => column.label).sort()).toEqual([
      "Backlog",
      "Done",
      "In progress",
    ]);
  });

  it("keeps the order the statement produced, which is the author's ORDER BY", async () => {
    const scene = await draw(work);
    expect(scene.columns.map((column) => column.label)).toEqual(["Backlog", "In progress", "Done"]);
  });

  it("puts the empty bucket last and names it after its column", async () => {
    const withGap = rows([
      ["Unfiled", null, T0, "Ada"],
      ["Filed", "Backlog", T0, "Ada"],
    ]);
    const scene = await draw(withGap);
    expect(scene.columns.map((column) => column.label)).toEqual(["Backlog", "No status"]);
  });

  it("orders columns by size when asked", async () => {
    const scene = await draw(work, { columns: "largest" });
    expect(scene.columns[0].label).toBe("In progress");
  });
});

describe("cards", () => {
  it("titles a card from the mapped card column", async () => {
    const scene = await draw(work);
    const backlog = scene.columns.find((column) => column.label === "Backlog");
    expect(backlog?.cards[0].title).toBe("Draft the brief");
  });

  it("marks a card whose date has passed", async () => {
    const scene = await draw(work);
    const inProgress = scene.columns.find((column) => column.label === "In progress");
    const late = inProgress?.cards.find((card) => card.title === "Wire the endpoint");
    expect(late?.tone).toBe("negative");
    expect(inProgress?.caption).toBe("1 late");
  });

  it("chips every other column, and never the one it is grouped by", async () => {
    const scene = await draw(work, { cards: "detailed" });
    const backlog = scene.columns.find((column) => column.label === "Backlog");
    expect(backlog?.cards[0].chips).toEqual(["Ada"]);
  });

  it("carries a title alone when asked to be compact", async () => {
    const scene = await draw(work, { cards: "compact" });
    const backlog = scene.columns.find((column) => column.label === "Backlog");
    expect(backlog?.cards[0].chips).toBeUndefined();
    expect(backlog?.cards[0].date).toBeUndefined();
  });

  it("orders cards by date when asked, with undated work last", async () => {
    const mixed = rows([
      ["Later", "Backlog", T0 + 9 * DAY, "Ada"],
      ["Someday", "Backlog", null, "Ada"],
      ["Sooner", "Backlog", T0 + 1 * DAY, "Ada"],
    ]);
    const scene = await draw(mixed, { sort: "date" });
    expect(scene.columns[0].cards.map((card) => card.title)).toEqual([
      "Sooner",
      "Later",
      "Someday",
    ]);
  });
});

describe("what it refuses to draw", () => {
  it("says so when it has no column to group by", async () => {
    const result = await renderInSandbox({
      source: builtinWidgetSource("board") as string,
      data: work,
      config: {},
      slots: { card: [0] },
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
