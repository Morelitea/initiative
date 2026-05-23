import { describe, expect, it } from "vitest";

import { buildQueue, buildQueueItem } from "@/__tests__/factories";

import {
  advanceQueueState,
  holdCurrentState,
  previousQueueState,
  releaseHeldState,
  resetQueueState,
  setActiveItemState,
  startQueueState,
  stopQueueState,
} from "./useQueues";

/**
 * These pure transitions back the optimistic turn-control cache updates and
 * must stay in lockstep with `_visible_items_desc` + advance/previous in
 * `backend/app/services/queues.py`. The cases below pin the ordering (descending
 * by position, including fractional positions), hidden-item skipping, and the
 * wrap-around round increment/decrement.
 */
describe("queue turn transitions", () => {
  // Positions are intentionally out of insertion order; turn order is by
  // position DESC, so the sequence should be c (30) → a (20) → b (10).
  const a = buildQueueItem({ id: 1, label: "a", position: 20 });
  const b = buildQueueItem({ id: 2, label: "b", position: 10 });
  const c = buildQueueItem({ id: 3, label: "c", position: 30 });

  const activeQueue = buildQueue({
    is_active: true,
    current_round: 1,
    items: [a, b, c],
    current_item: c,
  });

  describe("advanceQueueState", () => {
    it("moves to the next-lower position", () => {
      const next = advanceQueueState(activeQueue);
      expect(next.current_item?.id).toBe(a.id);
      expect(next.current_round).toBe(1);
    });

    it("wraps from the last item to the first and bumps the round", () => {
      const atLast = { ...activeQueue, current_item: b };
      const next = advanceQueueState(atLast);
      expect(next.current_item?.id).toBe(c.id);
      expect(next.current_round).toBe(2);
    });

    it("orders fractional positions between equal integers", () => {
      const lo = buildQueueItem({ id: 10, label: "lo", position: 10 });
      const mid = buildQueueItem({ id: 11, label: "mid", position: 10.5 });
      const hi = buildQueueItem({ id: 12, label: "hi", position: 11 });
      const queue = buildQueue({
        is_active: true,
        items: [lo, hi, mid],
        current_item: hi,
      });
      // hi (11) → mid (10.5) → lo (10)
      const second = advanceQueueState(queue);
      expect(second.current_item?.id).toBe(mid.id);
      const third = advanceQueueState(second);
      expect(third.current_item?.id).toBe(lo.id);
    });

    it("skips hidden items", () => {
      const hidden = { ...a, is_visible: false };
      const queue = buildQueue({
        is_active: true,
        items: [hidden, b, c],
        current_item: c,
      });
      // c (30) → b (10), skipping hidden a (20)
      const next = advanceQueueState(queue);
      expect(next.current_item?.id).toBe(b.id);
    });
  });

  describe("previousQueueState", () => {
    it("moves to the next-higher position", () => {
      const atA = { ...activeQueue, current_item: a };
      const prev = previousQueueState(atA);
      expect(prev.current_item?.id).toBe(c.id);
    });

    it("wraps from the first item to the last and decrements the round (min 1)", () => {
      const atFirstRound2 = { ...activeQueue, current_item: c, current_round: 2 };
      const prev = previousQueueState(atFirstRound2);
      expect(prev.current_item?.id).toBe(b.id);
      expect(prev.current_round).toBe(1);
    });

    it("never drops the round below 1", () => {
      const prev = previousQueueState({ ...activeQueue, current_item: c, current_round: 1 });
      expect(prev.current_round).toBe(1);
    });
  });

  describe("start / stop / reset", () => {
    it("start activates, selects the highest position, and resets the round", () => {
      const idle = buildQueue({ is_active: false, current_round: 5, items: [a, b, c] });
      const started = startQueueState(idle);
      expect(started.is_active).toBe(true);
      expect(started.current_item?.id).toBe(c.id);
      expect(started.current_round).toBe(1);
    });

    it("stop deactivates but keeps the current item", () => {
      const stopped = stopQueueState(activeQueue);
      expect(stopped.is_active).toBe(false);
      expect(stopped.current_item?.id).toBe(c.id);
    });

    it("reset returns to the highest position and round 1", () => {
      const mid = { ...activeQueue, current_item: b, current_round: 4 };
      const reset = resetQueueState(mid);
      expect(reset.current_item?.id).toBe(c.id);
      expect(reset.current_round).toBe(1);
    });
  });

  describe("setActiveItemState", () => {
    it("selects the requested item", () => {
      const result = setActiveItemState(activeQueue, a.id);
      expect(result.current_item?.id).toBe(a.id);
    });

    it("leaves the queue unchanged for an unknown item", () => {
      const result = setActiveItemState(activeQueue, 9999);
      expect(result).toBe(activeQueue);
    });
  });

  it("leaves an empty queue untouched", () => {
    const empty = buildQueue({ is_active: true, items: [], current_item: null });
    expect(advanceQueueState(empty)).toBe(empty);
    expect(previousQueueState(empty)).toBe(empty);
    expect(startQueueState(empty)).toBe(empty);
    expect(resetQueueState(empty)).toBe(empty);
  });
});

describe("hold / release", () => {
  // Helpful baseline: items A(30), B(20), C(10) — same shape the backend
  // tests exercise. Each `held` mutation here mirrors the matching backend
  // service call in `backend/app/services/queues.py`.
  const a = buildQueueItem({ id: 1, label: "A", position: 30 });
  const b = buildQueueItem({ id: 2, label: "B", position: 20 });
  const c = buildQueueItem({ id: 3, label: "C", position: 10 });
  const running = buildQueue({
    is_active: true,
    current_round: 1,
    items: [a, b, c],
    current_item: a,
  });

  describe("holdCurrentState", () => {
    it("stamps the current item with the current round and advances", () => {
      const held = holdCurrentState(running);
      expect(held.current_item?.id).toBe(b.id);
      expect(held.current_round).toBe(1);
      const heldA = held.items.find((i) => i.id === a.id);
      expect(heldA?.held_at_round).toBe(1);
    });

    it("clears the current when the only rotation-eligible item is held", () => {
      const solo = buildQueue({
        is_active: true,
        current_round: 1,
        items: [a],
        current_item: a,
      });
      const held = holdCurrentState(solo);
      expect(held.current_item).toBeNull();
      expect(held.items[0]?.held_at_round).toBe(1);
    });

    it("is a no-op when no current item is set", () => {
      const idle = { ...running, current_item: null };
      expect(holdCurrentState(idle)).toBe(idle);
    });
  });

  describe("advanceQueueState auto-release", () => {
    it("returns a held item to current when its slot comes around again", () => {
      // Hold A in round 1; advance past B, C, then wrap into round 2.
      const afterHold = holdCurrentState(running); // current = B, A held@1
      const afterB = advanceQueueState(afterHold); // current = C
      const afterC = advanceQueueState(afterB); // wraps → A auto-released
      expect(afterC.current_item?.id).toBe(a.id);
      expect(afterC.current_round).toBe(2);
      const releasedA = afterC.items.find((i) => i.id === a.id);
      expect(releasedA?.held_at_round).toBeNull();
    });

    it("skips a held item whose due round hasn't arrived yet", () => {
      // Hand-craft: B is held in round 1; current is A. Advancing from A
      // should land on C (skipping B), still in round 1.
      const queue = {
        ...running,
        items: [a, { ...b, held_at_round: 1 }, c],
        current_item: a,
      };
      const next = advanceQueueState(queue);
      expect(next.current_item?.id).toBe(c.id);
      expect(next.current_round).toBe(1);
      const stillHeldB = next.items.find((i) => i.id === b.id);
      expect(stillHeldB?.held_at_round).toBe(1);
    });
  });

  describe("previousQueueState", () => {
    it("skips held items without auto-release", () => {
      const queue = {
        ...running,
        items: [a, { ...b, held_at_round: 1 }, c],
        current_item: c,
      };
      const prev = previousQueueState(queue);
      // C → A (skipping held B); B remains held.
      expect(prev.current_item?.id).toBe(a.id);
      const stillHeldB = prev.items.find((i) => i.id === b.id);
      expect(stillHeldB?.held_at_round).toBe(1);
    });
  });

  describe("setActiveItemState clears held", () => {
    it("clears held_at_round on the target when promoting it to current", () => {
      const queue = {
        ...running,
        items: [{ ...a, held_at_round: 1 }, b, c],
        current_item: b,
      };
      const next = setActiveItemState(queue, a.id);
      expect(next.current_item?.id).toBe(a.id);
      expect(next.current_item?.held_at_round).toBeNull();
      const updatedA = next.items.find((i) => i.id === a.id);
      expect(updatedA?.held_at_round).toBeNull();
    });
  });

  describe("releaseHeldState", () => {
    it("clears the hold without rewinding the rotation pointer", () => {
      // Releasing should rejoin the rotation but not pull current back onto
      // an item the rotation already advanced past.
      const queue = {
        ...running,
        items: [{ ...a, held_at_round: 1 }, b, c],
        current_item: b,
      };
      const released = releaseHeldState(queue, a.id);
      expect(released.current_item?.id).toBe(b.id); // unchanged
      expect(released.current_round).toBe(1);
      const updatedA = released.items.find((i) => i.id === a.id);
      expect(updatedA?.held_at_round).toBeNull();
      // Default behavior: original position preserved.
      expect(updatedA?.position).toBe(a.position);
    });

    it("lifts the released item above current and promotes it to current", () => {
      // A is held; current=B(20). With A held there's nothing active above
      // B, so releasing A "here" should set A.position = B.position + 1 = 21
      // and make A the current turn — A acts now, before B does.
      const queue = {
        ...running,
        items: [{ ...a, held_at_round: 1 }, b, c],
        current_item: b,
      };
      const released = releaseHeldState(queue, a.id, { reposition: true });
      const updatedA = released.items.find((i) => i.id === a.id);
      expect(updatedA?.position).toBe(21);
      expect(released.current_item?.id).toBe(a.id);
    });

    it("lands between current and next-higher when one exists", () => {
      // B is held in the middle; current=C(10) with A(30) still above. Release
      // B with reposition → B.position lands at the midpoint between 10 and 30
      // (= 20), and B becomes current.
      const queue = {
        ...running,
        items: [a, { ...b, held_at_round: 1 }, c],
        current_item: c,
      };
      const released = releaseHeldState(queue, b.id, { reposition: true });
      const updatedB = released.items.find((i) => i.id === b.id);
      expect(updatedB?.position).toBe(20);
      expect(released.current_item?.id).toBe(b.id);
    });

    it("is a no-op if the target isn't held", () => {
      const released = releaseHeldState(running, b.id);
      expect(released).toBe(running);
    });
  });

  describe("startQueueState / resetQueueState skip held items", () => {
    it("start picks the highest un-held item", () => {
      const queue = buildQueue({
        is_active: false,
        items: [{ ...a, held_at_round: 1 }, b, c],
        current_item: null,
      });
      const started = startQueueState(queue);
      expect(started.current_item?.id).toBe(b.id);
    });

    it("reset jumps to the highest un-held item and preserves held state", () => {
      const queue = {
        ...running,
        items: [{ ...a, held_at_round: 1 }, b, c],
        current_item: c,
        current_round: 4,
      };
      const reset = resetQueueState(queue);
      expect(reset.current_item?.id).toBe(b.id);
      expect(reset.current_round).toBe(1);
      const stillHeldA = reset.items.find((i) => i.id === a.id);
      expect(stillHeldA?.held_at_round).toBe(1);
    });
  });
});
