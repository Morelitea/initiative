/**
 * The board through the whole path it takes in production: sandboxed module,
 * validator, scene. Asserted on the scene rather than on the DOM, because what
 * is worth pinning here is the widget's own reasoning — which column a task
 * lands in, which columns exist at all, and what order they come in — and none
 * of that is visible in a rendering.
 */
import { describe, expect, it } from "vitest";

import type { WidgetData } from "../dataShapes";
import { builtinWidgetSource } from "../registry";
import { renderInSandbox } from "../runtime/sandbox";
import { SAMPLE_NOW, sampleFor } from "../sampleData";
import type { BoardNode, SceneNode } from "../sceneSpec";
import { validateScene } from "../validateScene";

const run = async (config: Record<string, string>, data?: WidgetData): Promise<SceneNode> => {
  const result = await renderInSandbox({
    source: builtinWidgetSource("board") as string,
    data: data ?? sampleFor("tasks", "board"),
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
  return validation.spec.scene;
};

const draw = async (config: Record<string, string> = {}, data?: WidgetData): Promise<BoardNode> => {
  const scene = await run(config, data);
  expect(scene.kind).toBe("board");
  return scene as BoardNode;
};

const columnNamed = (board: BoardNode, label: string) => {
  const found = board.columns.find((column) => column.label === label);
  if (!found) {
    throw new Error(`no column ${label} in ${board.columns.map((c) => c.label).join(", ")}`);
  }
  return found;
};

const titles = (board: BoardNode, label: string) =>
  columnNamed(board, label).cards.map((card) => card.title);

describe("what a column stands for", () => {
  it("columns by status, ordered by the category its work sits in", async () => {
    const board = await draw();
    // "Blocked" is a to-do status, so it sits with the other to-dos rather than
    // wherever the rows happened to mention it first.
    expect(board.columns.map((column) => column.label)).toEqual([
      "To do",
      "Blocked",
      "In progress",
      "Done",
    ]);
    expect(titles(board, "In progress")).toContain("Migrate the search index");
  });

  it("puts work with two people on it under both of them", async () => {
    const board = await draw({ group: "assignee" });
    expect(titles(board, "Grace")).toContain("Ship the migration");
    expect(titles(board, "Ada")).toContain("Ship the migration");
  });

  it("gives work with nobody on it its own column, last", async () => {
    const board = await draw({ group: "assignee" });
    const last = board.columns[board.columns.length - 1];
    expect(last.label).toBe("Unassigned");
    expect(last.cards.map((card) => card.title)).toEqual(["Chase the vendor"]);
  });

  it("draws every rung of a fixed ladder, including the empty ones", async () => {
    const board = await draw({ group: "priority" });
    expect(board.columns.map((column) => column.label)).toEqual([
      "Urgent",
      "High",
      "Medium",
      "Low",
      "No priority",
    ]);
    // Nothing in the samples is urgent, and the column still exists.
    expect(columnNamed(board, "Urgent").cards).toEqual([]);
  });
});

describe("columns from a custom property", () => {
  it("reads the property the binding named", async () => {
    const board = await draw({ group: "property" });
    expect(titles(board, "Platform")).toContain("Draft the spec");
    expect(titles(board, "Growth")).toContain("Localize the emails");
  });

  it("keeps a declared value that nobody has used yet", async () => {
    const board = await draw({ group: "property" });
    // "Research" is an option on the property and on no task; a board that
    // dropped it would be hiding part of the workflow.
    expect(columnNamed(board, "Research").cards).toEqual([]);
  });

  it("collects tasks with no value into their own column", async () => {
    const board = await draw({ group: "property" });
    expect(titles(board, "Not set")).toEqual(["Chase the vendor"]);
  });

  it("asks for the property instead of drawing an empty board", async () => {
    const sample = sampleFor("tasks", "board") as Extract<WidgetData, { source: "tasks" }>;
    const scene = await run({ group: "property" }, { ...sample, property: undefined });
    expect(scene.kind).toBe("empty");
  });
});

describe("cards", () => {
  it("marks work that is past its date and still open", async () => {
    const board = await draw();
    const late = columnNamed(board, "Blocked").cards[0];
    expect(late).toMatchObject({ title: "Chase the vendor", tone: "negative" });
    expect(columnNamed(board, "Blocked").caption).toBe("1 late");
  });

  it("leaves finished work alone, however old its due date", async () => {
    const board = await draw();
    for (const card of columnNamed(board, "Done").cards) expect(card.tone).toBeUndefined();
  });

  it("does not repeat the column's own field on the cards inside it", async () => {
    const byPerson = await draw({ group: "assignee" });
    expect(columnNamed(byPerson, "Ada").cards[0].chips ?? []).not.toContain("Ada");

    const byStatus = await draw({ group: "status" });
    expect(columnNamed(byStatus, "In progress").cards[0].chips).toContain("Grace");
  });

  it("carries checklist progress as both a caption and a bar", async () => {
    const board = await draw();
    const card = columnNamed(board, "In progress").cards.find(
      (entry) => entry.title === "Migrate the search index"
    );
    expect(card).toMatchObject({ caption: "1/4", progress: 0.25 });
  });

  it("reduces to titles when asked for", async () => {
    const board = await draw({ cards: "compact" });
    for (const column of board.columns) {
      for (const card of column.cards) {
        expect(card.chips).toBeUndefined();
        expect(card.date).toBeUndefined();
        expect(card.caption).toBeUndefined();
      }
    }
  });
});

describe("order", () => {
  it("sorts by due date with undated work at the foot", async () => {
    const board = await draw({ group: "status_category", sort: "due" });
    const todo = columnNamed(board, "To do");
    const dated = todo.cards.filter((card) => card.date !== undefined);
    expect(dated.map((card) => card.date)).toEqual(
      [...dated.map((card) => card.date as number)].sort((a, b) => a - b)
    );
    const undated = todo.cards.findIndex((card) => card.date === undefined);
    if (undated !== -1) expect(undated).toBe(todo.cards.length - 1);
  });

  it("puts the fullest column first when asked", async () => {
    const board = await draw({ group: "assignee", columns: "largest" });
    const sizes = board.columns.map((column) => column.cards.length);
    expect(sizes).toEqual([...sizes].sort((a, b) => b - a));
  });
});
