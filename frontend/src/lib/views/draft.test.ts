import { describe, expect, it } from "vitest";

import { buildPropertyDefinition } from "@/__tests__/factories";
import type { ToolViewWrite } from "@/api/generated/initiativeAPI.schemas";

import {
  addableFields,
  changeAt,
  historyReducer,
  indexPaths,
  insertAt,
  moveWithin,
  nodeAt,
  pathAfterMove,
  pathAfterRemove,
  removable,
  startHistory,
} from "./draft";
import { taskFields } from "./tasks";
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

describe("what the editor allows", () => {
  const fields = taskFields([buildPropertyDefinition({ id: 12, name: "Effort" })]);

  it("never takes off the title, nor a group that holds it", () => {
    expect(removable(field("tags"), fields)).toBe(true);
    expect(removable(field("title"), fields)).toBe(false);
    expect(removable(nodeAt(CARD, [0]) as ViewNode, fields)).toBe(false);
  });

  it("offers a card what it does not show, and no property alone where it shows them all", () => {
    const ids = (card: ViewNode) =>
      addableFields({ layout: { type: "board" }, card: card as never }, fields).map(
        (each) => each.id
      );

    expect(ids(CARD)).not.toContain("tags");
    expect(ids(CARD)).toContain("property:12");
    expect(
      ids({ ...CARD, children: [...(CARD.children ?? []), { type: "properties" }] })
    ).not.toContain("property:12");
  });

  it("offers a table the fields it draws as columns and has not", () => {
    const ids = addableFields(
      { layout: { type: "table" }, columns: ["title", "dueDate"] },
      fields
    ).map((each) => each.id);

    expect(ids).toEqual(["startDate", "priority", "comments", "tags", "property:12"]);
  });
});

describe("a selection as the card changes", () => {
  it("follows the part it names when parts move", () => {
    // The group's third part moves to the front.
    expect(pathAfterMove([0, 2], [0], 2, 0)).toEqual([0, 0]);
    expect(pathAfterMove([0, 0], [0], 2, 0)).toEqual([0, 1]);
    expect(pathAfterMove([0, 3, 1], [0], 2, 0)).toEqual([0, 3, 1]);
    expect(pathAfterMove([1], [0], 2, 0)).toEqual([1]);
  });

  it("closes up after a part is taken out, and is gone with it", () => {
    expect(pathAfterRemove([0, 2], [0, 1])).toEqual([0, 1]);
    expect(pathAfterRemove([0, 0], [0, 1])).toEqual([0, 0]);
    expect(pathAfterRemove([0, 1, 3], [0, 1])).toBeNull();
    expect(pathAfterRemove([1], [0, 1])).toEqual([1]);
  });
});
