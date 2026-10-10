import { describe, expect, it } from "vitest";

import type { ToolViewWrite } from "@/api/generated/initiativeAPI.schemas";

import {
  changeAt,
  historyReducer,
  indexPaths,
  insertAt,
  moveWithin,
  nodeAt,
  startHistory,
} from "./draft";
import type { ViewNode } from "./tree";

const field = (id: string): ViewNode => ({ type: "field", props: { field: id } });

const CARD: ViewNode = {
  type: "card",
  children: [{ type: "stack", children: [field("title"), field("description")] }, field("tags")],
};

describe("editing a tree by path", () => {
  it("changes or takes out one node and leaves the rest as they were", () => {
    const renamed = changeAt(CARD, [0, 1], () => field("priority"));
    const removed = changeAt(CARD, [0, 0], () => null);

    expect(nodeAt(renamed, [0, 1])).toEqual(field("priority"));
    expect(renamed.children?.[1]).toBe(CARD.children?.[1]);
    expect(nodeAt(removed, [0])?.children).toEqual([field("description")]);
    expect(nodeAt(CARD, [0])?.children).toHaveLength(2);
  });

  it("puts a node into a group, and moves one within its group", () => {
    const added = insertAt(CARD, [0], field("priority"), 1);
    const moved = moveWithin(CARD, [0], 0, 1);

    expect(nodeAt(added, [0])?.children?.map((node) => node.props?.field)).toEqual([
      "title",
      "priority",
      "description",
    ]);
    expect(nodeAt(moved, [0])?.children?.map((node) => node.props?.field)).toEqual([
      "description",
      "title",
    ]);
  });

  it("names every node by its path", () => {
    const paths = indexPaths(CARD);

    expect(paths.get(CARD)).toBe("");
    expect(paths.get(nodeAt(CARD, [0, 1]) as ViewNode)).toBe("0.1");
  });
});

describe("historyReducer", () => {
  const view = (name: string): ToolViewWrite[] => [
    { name, definition: { layout: { type: "board" } } },
  ];

  it("undoes and redoes each change, and a new change ends what could be redone", () => {
    let history = startHistory(view("A"));
    history = historyReducer(history, { type: "change", views: view("B") });
    history = historyReducer(history, { type: "change", views: view("C") });

    history = historyReducer(history, { type: "undo" });
    expect(history.present[0].name).toBe("B");
    history = historyReducer(history, { type: "redo" });
    expect(history.present[0].name).toBe("C");

    history = historyReducer(history, { type: "undo" });
    history = historyReducer(history, { type: "change", views: view("D") });
    expect(history.future).toEqual([]);
    expect(historyReducer(history, { type: "reset", views: view("A") })).toEqual(
      startHistory(view("A"))
    );
  });
});
