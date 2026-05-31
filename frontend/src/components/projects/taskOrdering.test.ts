import { describe, expect, it } from "vitest";

import { computeMidpoint, reorderTaskList, shouldInsertAfter } from "./taskOrdering";

describe("computeMidpoint", () => {
  it("returns the midpoint between two neighbors", () => {
    const tasks = [{ position: 1 }, { position: 2 }];
    // Insert at index 1 -> between position 1 and 2.
    expect(computeMidpoint(tasks, 1)).toBe(1.5);
  });

  it("returns one less than the first task when inserting at the top", () => {
    const tasks = [{ position: 5 }, { position: 6 }];
    expect(computeMidpoint(tasks, 0)).toBe(4);
  });

  it("returns one more than the last task when inserting at the bottom", () => {
    const tasks = [{ position: 1 }, { position: 2 }];
    expect(computeMidpoint(tasks, 2)).toBe(3);
  });

  it("returns 0 for an empty list", () => {
    expect(computeMidpoint([], 0)).toBe(0);
  });

  it("produces a fractional value between fractional neighbors", () => {
    const tasks = [{ position: 1.5 }, { position: 1.75 }];
    expect(computeMidpoint(tasks, 1)).toBe(1.625);
  });

  it("clamps precision to 10 decimal places", () => {
    const tasks = [{ position: 1 }, { position: 1.0000000001 }];
    const result = computeMidpoint(tasks, 1);
    // (1 + 1.0000000001) / 2 = 1.00000000005, rounded to 10 dp.
    expect(result).toBe(Number((1.00000000005).toFixed(10)));
  });
});

describe("shouldInsertAfter", () => {
  it("returns true when the dragged card's center is below the target's", () => {
    const active = { top: 100, height: 40 }; // center 120
    const over = { top: 90, height: 40 }; // center 110
    expect(shouldInsertAfter(active, over)).toBe(true);
  });

  it("returns false when the dragged card's center is above the target's", () => {
    const active = { top: 80, height: 40 }; // center 100
    const over = { top: 100, height: 40 }; // center 120
    expect(shouldInsertAfter(active, over)).toBe(false);
  });

  it("defaults to false (insert before) when a rect is missing", () => {
    expect(shouldInsertAfter(null, { top: 0, height: 40 })).toBe(false);
    expect(shouldInsertAfter({ top: 0, height: 40 }, undefined)).toBe(false);
  });
});

describe("reorderTaskList", () => {
  // A simple project: two statuses (1 = Todo, 2 = Done), global order by index.
  const todo = (id: number) => ({ id, task_status_id: 1 });
  const done = (id: number) => ({ id, task_status_id: 2 });
  const ids = <T extends { id: number }>(tasks: T[]) => tasks.map((t) => t.id);

  it("moves the top card below the second when dropped after it", () => {
    const base = [todo(1), todo(2), todo(3)];
    const result = reorderTaskList(base, todo(1), 2, true, 1);
    expect(ids(result)).toEqual([2, 1, 3]);
  });

  it("keeps the card before the target when dropped above it", () => {
    const base = [todo(1), todo(2), todo(3)];
    const result = reorderTaskList(base, todo(3), 1, false, 1);
    expect(ids(result)).toEqual([3, 1, 2]);
  });

  it("reaches the first slot of another column when dropped above its first card", () => {
    const base = [todo(1), done(2), done(3)];
    // Move task 1 into the Done column, above its first card (2).
    const moved = { id: 1, task_status_id: 2 };
    const result = reorderTaskList(base, moved, 2, false, 2);
    expect(ids(result)).toEqual([1, 2, 3]);
    expect(result.find((t) => t.id === 1)?.task_status_id).toBe(2);
  });

  it("reaches the second slot of another column when dropped below its first card", () => {
    const base = [todo(1), done(2), done(3)];
    const moved = { id: 1, task_status_id: 2 };
    const result = reorderTaskList(base, moved, 2, true, 2);
    expect(ids(result)).toEqual([2, 1, 3]);
  });

  it("appends to the end of the target column when dropped on empty body", () => {
    const base = [todo(1), todo(2), done(3)];
    // Move task 1 into Done with no specific target card.
    const moved = { id: 1, task_status_id: 2 };
    const result = reorderTaskList(base, moved, null, false, 2);
    // Inserted right after the last Done card (3).
    expect(ids(result)).toEqual([2, 3, 1]);
  });

  it("appends as the first card when the target column is empty", () => {
    const base = [todo(1), todo(2)];
    const moved = { id: 1, task_status_id: 2 };
    const result = reorderTaskList(base, moved, null, false, 2);
    // No existing Done card -> lastIndex stays -1 -> inserted at front.
    expect(ids(result)).toEqual([1, 2]);
    expect(result[0].task_status_id).toBe(2);
  });
});
