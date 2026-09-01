import { describe, expect, it } from "vitest";

import type { ChesterToastType } from "./chesterToast";
import { computeAutoClose } from "./chesterToast";

const TYPE_SPEED = 20;

/** What the reader actually experiences: the typing animation plus the dwell after it. */
const totalOnScreen = (message: string, type: ChesterToastType, hasAction = false) =>
  message.length * TYPE_SPEED + computeAutoClose(message, type, TYPE_SPEED, hasAction);

describe("computeAutoClose", () => {
  it("holds a short toast for the per-type floor", () => {
    expect(totalOnScreen("Saved", "success")).toBe(3_000);
  });

  it("scales with message length", () => {
    expect(totalOnScreen("Task created".repeat(8), "default")).toBeGreaterThan(
      totalOnScreen("Task created", "default")
    );
  });

  it("gives warnings and errors a longer floor than neutral toasts", () => {
    expect(totalOnScreen("Nope", "warning")).toBeGreaterThan(totalOnScreen("Nope", "info"));
    expect(totalOnScreen("Nope", "error")).toBeGreaterThan(totalOnScreen("Nope", "warning"));
  });

  it("adds time when the toast has an action to click", () => {
    const message = "Project archived. It can be restored from the trash at any time.";
    expect(totalOnScreen(message, "success", true)).toBe(totalOnScreen(message, "success") + 2_000);
  });

  it("caps the reading budget so a long message does not camp on screen", () => {
    // With no typing animation the dwell is the whole budget, which is clamped.
    expect(computeAutoClose("x".repeat(400), "default", 0, false)).toBe(10_000);
  });

  it("always leaves a dwell after typing finishes", () => {
    // Typing alone (600 chars × 20ms) already outruns the budget.
    expect(computeAutoClose("x".repeat(600), "default", TYPE_SPEED, false)).toBe(1_200);
  });

  it("is shorter than the old fixed 5s dwell for a typical toast", () => {
    expect(computeAutoClose("Task created", "success", TYPE_SPEED, false)).toBeLessThan(5_000);
  });
});
