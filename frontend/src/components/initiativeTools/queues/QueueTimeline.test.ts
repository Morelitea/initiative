import { describe, expect, it } from "vitest";

import { buildQueue, buildQueueItem } from "@/__tests__/factories";

import { buildTimeline, type TimelineRow } from "./QueueTimeline";

/**
 * Build a queue where visible items, sorted by position descending, are
 * [A, B, C]. Tests below tweak `current_item`, `current_round`, and
 * `is_active` on top of this baseline.
 */
const a = buildQueueItem({ id: 1, label: "A", position: 30 });
const b = buildQueueItem({ id: 2, label: "B", position: 20 });
const c = buildQueueItem({ id: 3, label: "C", position: 10 });

const baseQueue = buildQueue({
  is_active: true,
  current_round: 1,
  // Insertion order intentionally out of sort order to exercise sorting.
  items: [b, a, c],
  current_item: a,
});

const labels = (rows: TimelineRow[]): string[] =>
  rows.map((row) => {
    if (row.kind === "round-divider") return `--R${row.round}--`;
    if (row.kind === "hidden-divider") return "--Hidden--";
    if (row.kind === "held-divider") return "--Held--";
    return row.item.label;
  });

describe("buildTimeline", () => {
  it("pins the round divider at the end when current is at the top", () => {
    // Constant row count is important so the View Transitions API can morph
    // the divider's position smoothly across turns.
    expect(labels(buildTimeline(baseQueue))).toEqual(["A", "B", "C", "--R2--"]);
  });

  it("rotates and moves the round divider into the rotation as turns advance", () => {
    // Current = B: round-1 items are B, C; A rolls into round 2 behind the divider.
    const rotated = { ...baseQueue, current_item: b };
    expect(labels(buildTimeline(rotated))).toEqual(["B", "C", "--R2--", "A"]);
  });

  it("places the divider immediately after the last current-round item", () => {
    const tailQueue = { ...baseQueue, current_item: c };
    expect(labels(buildTimeline(tailQueue))).toEqual(["C", "--R2--", "A", "B"]);
  });

  it("keeps a constant row count across every turn so the divider can morph in place", () => {
    // The same items at every rotation step — only the divider's slot moves.
    const states = [a, b, c].map((current) => ({ ...baseQueue, current_item: current }));
    const rowCounts = states.map((q) => buildTimeline(q).length);
    expect(new Set(rowCounts).size).toBe(1);
  });

  it("reflects the queue's current_round on divider labels", () => {
    const round5 = { ...baseQueue, current_item: c, current_round: 5 };
    const rows = buildTimeline(round5);
    const divider = rows.find((r) => r.kind === "round-divider");
    expect(divider).toEqual({ kind: "round-divider", round: 6 });
  });

  it("orders fractional positions between equal integers", () => {
    const lo = buildQueueItem({ id: 10, label: "lo", position: 10 });
    const mid = buildQueueItem({ id: 11, label: "mid", position: 10.5 });
    const hi = buildQueueItem({ id: 12, label: "hi", position: 11 });
    const queue = buildQueue({
      is_active: true,
      current_round: 1,
      items: [lo, hi, mid],
      current_item: hi,
    });
    expect(labels(buildTimeline(queue))).toEqual(["hi", "mid", "lo", "--R2--"]);
  });

  it("shows hidden items below a 'Hidden' divider so they remain editable", () => {
    const hidden = { ...a, is_visible: false };
    const queue = { ...baseQueue, items: [hidden, b, c], current_item: b };
    expect(labels(buildTimeline(queue))).toEqual(["B", "C", "--R2--", "--Hidden--", "A"]);
  });

  it("omits the round divider when the queue isn't running", () => {
    const idle = {
      ...baseQueue,
      is_active: false,
      current_item: null,
      items: [a, b, c],
    };
    expect(labels(buildTimeline(idle))).toEqual(["A", "B", "C"]);
  });

  it("re-sorts to default order when the queue is stopped mid-rotation", () => {
    // Backend keeps `current_item_id` after stop, but the user expects the
    // visual rotation to reset to position-desc so the list doesn't stay
    // frozen wherever the previous run left off.
    const stoppedMidRotation = {
      ...baseQueue,
      is_active: false,
      current_item: b,
      current_round: 4,
      items: [a, b, c],
    };
    expect(labels(buildTimeline(stoppedMidRotation))).toEqual(["A", "B", "C"]);
  });

  it("still shows hidden items when there are no visible items", () => {
    const onlyHidden = { ...a, is_visible: false };
    const queue = buildQueue({ is_active: true, items: [onlyHidden], current_item: null });
    expect(labels(buildTimeline(queue))).toEqual(["--Hidden--", "A"]);
  });

  it("returns an empty timeline for a queue with no items at all", () => {
    const empty = buildQueue({ is_active: true, items: [], current_item: null });
    expect(buildTimeline(empty)).toEqual([]);
  });

  it("renders held items above the rotation in a Held section", () => {
    // A is held in round 1; current is B. Expected rows:
    //   [Held] A | B (current) | C | [R2] (pinned)
    const queue = {
      ...baseQueue,
      items: [{ ...a, held_at_round: 1 }, b, c],
      current_item: b,
    };
    expect(labels(buildTimeline(queue))).toEqual(["--Held--", "A", "B", "C", "--R2--"]);
  });

  it("sorts the Held section by position-desc", () => {
    const queue = {
      ...baseQueue,
      items: [
        { ...a, held_at_round: 1 }, // pos 30
        { ...c, held_at_round: 1 }, // pos 10
        b, // active
      ],
      current_item: b,
    };
    // Held block: A (30), C (10); rotation: B; then trailing R2 divider.
    expect(labels(buildTimeline(queue))).toEqual(["--Held--", "A", "C", "B", "--R2--"]);
  });

  it("renders Held + Hidden together when both exist", () => {
    const queue = {
      ...baseQueue,
      items: [{ ...a, held_at_round: 1 }, b, { ...c, is_visible: false }],
      current_item: b,
    };
    expect(labels(buildTimeline(queue))).toEqual([
      "--Held--",
      "A",
      "B",
      "--R2--",
      "--Hidden--",
      "C",
    ]);
  });

  it("doesn't render a Held section when no items are held", () => {
    const rows = buildTimeline(baseQueue);
    expect(rows.some((row) => row.kind === "held-divider")).toBe(false);
  });
});
