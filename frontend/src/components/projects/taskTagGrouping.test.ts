import { describe, expect, it } from "vitest";

import { buildTagSummary, buildTask } from "@/__tests__/factories";

import {
  collectTagsByName,
  fanOutTasksByTag,
  type TaskTagRow,
  tagRowId,
  uniqueTasksFromRows,
} from "./taskTagGrouping";

const bug = buildTagSummary({ name: "bug" });
const urgent = buildTagSummary({ name: "urgent" });

describe("fanOutTasksByTag", () => {
  it("emits one row per tag so a task shows up under each of its tags", () => {
    const task = buildTask({ tags: [bug, urgent] });

    const rows = fanOutTasksByTag([task], "Untagged");

    expect(rows).toHaveLength(2);
    expect(rows.map((row) => row.tagGroup)).toEqual(["bug", "urgent"]);
    expect(rows.every((row) => row.id === task.id)).toBe(true);
  });

  it("puts tasks without tags in the untagged group", () => {
    const rows = fanOutTasksByTag([buildTask({ tags: [] }), buildTask({ tags: [] })], "Untagged");

    expect(rows.map((row) => row.tagGroup)).toEqual(["Untagged", "Untagged"]);
  });

  it("leaves the source tasks untouched", () => {
    const task = buildTask({ tags: [bug] });

    fanOutTasksByTag([task], "Untagged");

    expect("tagGroup" in task).toBe(false);
  });
});

describe("tagRowId", () => {
  it("keeps the plain task id when the table is not grouped by tag", () => {
    expect(tagRowId(buildTask({ id: 7 }))).toBe("7");
  });

  it("distinguishes the rows of one task across groups", () => {
    const rows = fanOutTasksByTag([buildTask({ id: 7, tags: [bug, urgent] })], "Untagged");

    expect(rows.map(tagRowId)).toEqual(["7::bug", "7::urgent"]);
  });
});

describe("collectTagsByName", () => {
  it("maps every tag name seen on the tasks back to its tag", () => {
    const byName = collectTagsByName([buildTask({ tags: [bug, urgent] }), buildTask({ tags: [] })]);

    expect(byName.get("bug")).toBe(bug);
    expect(byName.get("urgent")).toBe(urgent);
    expect(byName.size).toBe(2);
  });
});

describe("uniqueTasksFromRows", () => {
  it("collapses a task's rows to the original task object", () => {
    const tagged = buildTask({ tags: [bug, urgent] });
    const untagged = buildTask({ tags: [] });
    const tasksById = new Map([tagged, untagged].map((task) => [task.id, task]));

    const selected = uniqueTasksFromRows(
      fanOutTasksByTag([tagged, untagged], "Untagged"),
      tasksById
    );

    expect(selected).toEqual([tagged, untagged]);
    expect(selected[0]).toBe(tagged);
  });

  it("falls back to the row when the task is no longer in the list", () => {
    const row: TaskTagRow = { ...buildTask({ id: 42, tags: [bug] }), tagGroup: "bug" };

    expect(uniqueTasksFromRows([row], new Map())).toEqual([row]);
  });
});
