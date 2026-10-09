import { describe, expect, it } from "vitest";

import { isKanbanFieldVisible, kanbanFieldsStorageKey } from "@/components/projects/kanbanFields";

describe("isKanbanFieldVisible", () => {
  it("shows anything the reader has not turned off", () => {
    // The default has to be "shown": a board nobody has configured must look
    // exactly as it did before the menu existed.
    expect(isKanbanFieldVisible({}, "priority")).toBe(true);
    expect(isKanbanFieldVisible({ priority: true }, "priority")).toBe(true);
    expect(isKanbanFieldVisible({ tags: false }, "priority")).toBe(true);
  });

  it("hides only what is explicitly off", () => {
    expect(isKanbanFieldVisible({ priority: false }, "priority")).toBe(false);
  });
});

describe("kanbanFieldsStorageKey", () => {
  it("is per project, so two boards keep separate choices", () => {
    expect(kanbanFieldsStorageKey(1)).not.toBe(kanbanFieldsStorageKey(2));
  });
});
