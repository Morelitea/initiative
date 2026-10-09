/**
 * The create dialog places every field it holds.
 *
 * The dialog shows its fields by `TASK_FORM_SECTIONS`, and this asserts that
 * definition covers `TaskFormValue` exactly — add a field to the value without
 * giving it a section and this fails.
 */
import { describe, expect, it } from "vitest";

import { emptyTaskFormValue, TASK_FORM_SECTIONS } from "@/components/tasks/TaskForm";

describe("TASK_FORM_SECTIONS", () => {
  it("gives every field of a task form value exactly one section", () => {
    const placed = TASK_FORM_SECTIONS.flatMap((section) => [...section.keys]);
    const all = Object.keys(emptyTaskFormValue());

    expect([...placed].sort()).toEqual([...all].sort());
  });

  it("places each field only once", () => {
    const placed = TASK_FORM_SECTIONS.flatMap((section) => [...section.keys]);

    expect(new Set(placed).size).toBe(placed.length);
  });
});
