import { describe, expect, it } from "vitest";

import { TaskPriority } from "@/api/generated/initiativeAPI.schemas";

import { PRIORITY_ORDER, priorityRank } from "./sorting";

describe("priority ordering", () => {
  it("ranks every backend priority low → urgent", () => {
    expect(priorityRank.low).toBeLessThan(priorityRank.medium);
    expect(priorityRank.medium).toBeLessThan(priorityRank.high);
    expect(priorityRank.high).toBeLessThan(priorityRank.urgent);
  });

  it("covers every value of the generated TaskPriority enum", () => {
    // Guards against drift from the backend: a newly added priority must
    // appear here (and get ranked) or these assertions fail.
    const enumValues = Object.values(TaskPriority);
    expect(new Set(PRIORITY_ORDER)).toEqual(new Set(enumValues));
    expect(Object.keys(priorityRank).sort()).toEqual([...enumValues].sort());
  });

  it("orders PRIORITY_ORDER ascending by rank", () => {
    expect(PRIORITY_ORDER).toEqual(["low", "medium", "high", "urgent"]);
    const ranks = PRIORITY_ORDER.map((p) => priorityRank[p]);
    expect(ranks).toEqual([...ranks].sort((a, b) => a - b));
  });

  it("sorts urgent ahead of low when used descending (dashboard tiebreaker)", () => {
    // Regression for #863: urgent tasks must not sort last.
    const byUrgentFirst = [TaskPriority.low, TaskPriority.urgent, TaskPriority.medium].sort(
      (a, b) => priorityRank[b] - priorityRank[a]
    );
    expect(byUrgentFirst[0]).toBe(TaskPriority.urgent);
  });
});
