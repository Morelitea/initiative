import { describe, expect, it } from "vitest";

import type { CellRange } from "./coords";
import { type CellValue, keyOf } from "./coords";
import { computeAutofillTarget, computeFillWrites } from "./fill";

// Build a reader over a sparse "r:c" → value record.
const reader =
  (data: Record<string, CellValue>) =>
  (r: number, c: number): CellValue =>
    data[keyOf(r, c)] ?? null;

// Collapse the writes Map to a plain record for easy assertions.
const writesAt = (m: Map<string, CellValue>) => Object.fromEntries(m);

const box = (r1: number, r2: number, c1: number, c2: number): CellRange => ({ r1, r2, c1, c2 });

describe("computeFillWrites — formulas", () => {
  it("translates relative references when filling down", () => {
    const read = reader({ [keyOf(0, 1)]: "=A1" }); // B1 = A1
    const w = writesAt(computeFillWrites(read, box(0, 0, 1, 1), box(0, 2, 1, 1)));
    expect(w).toEqual({ [keyOf(1, 1)]: "=A2", [keyOf(2, 1)]: "=A3" });
  });

  it("translates references when filling right", () => {
    const read = reader({ [keyOf(1, 0)]: "=A1" }); // A2 = A1
    const w = writesAt(computeFillWrites(read, box(1, 1, 0, 0), box(1, 1, 0, 2)));
    expect(w).toEqual({ [keyOf(1, 1)]: "=B1", [keyOf(1, 2)]: "=C1" });
  });

  it("emits #REF! when a relative reference is pulled off-grid", () => {
    const read = reader({ [keyOf(2, 0)]: "=A1" }); // A3 = A1
    // Fill up from A3: the cell just above references row -1, and the one
    // above that row -2 — both off the top of the grid.
    const w = writesAt(computeFillWrites(read, box(2, 2, 0, 0), box(0, 2, 0, 0)));
    expect(w[keyOf(1, 0)]).toBe("=#REF!");
    expect(w[keyOf(0, 0)]).toBe("=#REF!");
  });
});

describe("computeFillWrites — numeric series", () => {
  it("copies a single number (step 0)", () => {
    const read = reader({ [keyOf(0, 0)]: 5 });
    const w = writesAt(computeFillWrites(read, box(0, 0, 0, 0), box(0, 2, 0, 0)));
    expect(w).toEqual({ [keyOf(1, 0)]: 5, [keyOf(2, 0)]: 5 });
  });

  it("extrapolates an arithmetic progression downward", () => {
    const read = reader({ [keyOf(0, 0)]: 1, [keyOf(1, 0)]: 2 });
    const w = writesAt(computeFillWrites(read, box(0, 1, 0, 0), box(0, 4, 0, 0)));
    expect(w).toEqual({ [keyOf(2, 0)]: 3, [keyOf(3, 0)]: 4, [keyOf(4, 0)]: 5 });
  });

  it("extrapolates upward (continuing the progression outward)", () => {
    const read = reader({ [keyOf(3, 0)]: 10, [keyOf(4, 0)]: 20 });
    const w = writesAt(computeFillWrites(read, box(3, 4, 0, 0), box(1, 4, 0, 0)));
    // n = r - source.r1 (=3): row 2 → n=-1 → 0, row 1 → n=-2 → -10.
    expect(w).toEqual({ [keyOf(2, 0)]: 0, [keyOf(1, 0)]: -10 });
  });

  it("rounds to the seeds' precision instead of leaking float drift", () => {
    const read = reader({ [keyOf(0, 0)]: 0.1, [keyOf(1, 0)]: 0.2 });
    const w = writesAt(computeFillWrites(read, box(0, 1, 0, 0), box(0, 6, 0, 0)));
    // Naive 0.1 + 0.1*n would give 0.30000000000000004, 0.7000000000000001, …
    expect(w).toEqual({
      [keyOf(2, 0)]: 0.3,
      [keyOf(3, 0)]: 0.4,
      [keyOf(4, 0)]: 0.5,
      [keyOf(5, 0)]: 0.6,
      [keyOf(6, 0)]: 0.7,
    });
  });

  it("preserves multi-decimal precision when seeds warrant it", () => {
    const read = reader({ [keyOf(0, 0)]: 1.25, [keyOf(1, 0)]: 1.5 });
    const w = writesAt(computeFillWrites(read, box(0, 1, 0, 0), box(0, 3, 0, 0)));
    expect(w).toEqual({ [keyOf(2, 0)]: 1.75, [keyOf(3, 0)]: 2 });
  });

  it("rounds decimals when filling upward (negative offset)", () => {
    // Seeds at rows 3-4 (0.5, 0.6); filling up exercises the negative-n path.
    const read = reader({ [keyOf(3, 0)]: 0.5, [keyOf(4, 0)]: 0.6 });
    const w = writesAt(computeFillWrites(read, box(3, 4, 0, 0), box(0, 4, 0, 0)));
    // n = r - 3: row 2 → 0.4, row 1 → 0.3, row 0 → 0.2 — no float drift.
    expect(w).toEqual({ [keyOf(2, 0)]: 0.4, [keyOf(1, 0)]: 0.3, [keyOf(0, 0)]: 0.2 });
  });
});

describe("computeFillWrites — text+integer series", () => {
  it("increments a single text+integer cell by one", () => {
    const read = reader({ [keyOf(0, 0)]: "Item 1" });
    const w = writesAt(computeFillWrites(read, box(0, 0, 0, 0), box(0, 2, 0, 0)));
    expect(w).toEqual({ [keyOf(1, 0)]: "Item 2", [keyOf(2, 0)]: "Item 3" });
  });

  it("follows an established suffix step and keeps zero-padding", () => {
    const read = reader({ [keyOf(0, 0)]: "Q01", [keyOf(1, 0)]: "Q03" });
    const w = writesAt(computeFillWrites(read, box(0, 1, 0, 0), box(0, 3, 0, 0)));
    expect(w).toEqual({ [keyOf(2, 0)]: "Q05", [keyOf(3, 0)]: "Q07" });
  });
});

describe("computeFillWrites — tiling fallback", () => {
  it("tiles plain text verbatim", () => {
    const read = reader({ [keyOf(0, 0)]: "abc" });
    const w = writesAt(computeFillWrites(read, box(0, 0, 0, 0), box(0, 2, 0, 0)));
    expect(w).toEqual({ [keyOf(1, 0)]: "abc", [keyOf(2, 0)]: "abc" });
  });

  it("tiles a mixed formula+value line, translating only the formula", () => {
    // Source rows: A1 = "x" (text), A2 = =B2 (formula). Mixed → no series.
    const read = reader({ [keyOf(0, 0)]: "x", [keyOf(1, 0)]: "=B2" });
    const w = writesAt(computeFillWrites(read, box(0, 1, 0, 0), box(0, 3, 0, 0)));
    // Tiling continues the 2-tall pattern: row2→"x", row3→=B4 (shifted +2).
    expect(w).toEqual({ [keyOf(2, 0)]: "x", [keyOf(3, 0)]: "=B4" });
  });

  it("clears a destination cell when its source cell is empty", () => {
    // Source column has data only in row 0; row 1 is empty.
    const read = reader({ [keyOf(0, 0)]: "x" });
    const w = computeFillWrites(read, box(0, 1, 0, 0), box(0, 3, 0, 0));
    expect(w.get(keyOf(2, 0))).toBe("x"); // tiles from row 0
    expect(w.get(keyOf(3, 0))).toBe(null); // tiles from empty row 1 → clear
  });
});

describe("computeAutofillTarget", () => {
  const dims = { rows: 100, cols: 26 };

  it("extends down to the neighboring column's contiguous extent", () => {
    const read = reader({
      [keyOf(0, 0)]: "a",
      [keyOf(1, 0)]: "b",
      [keyOf(2, 0)]: "c", // column A has data rows 0-2
      [keyOf(0, 1)]: "=A1", // source B1
    });
    expect(computeAutofillTarget(read, box(0, 0, 1, 1), dims)).toEqual(box(0, 2, 1, 1));
  });

  it("falls back to the right neighbor when the left has none", () => {
    const read = reader({
      [keyOf(0, 1)]: 1,
      [keyOf(1, 1)]: 1, // column B (right of source A) has data rows 0-1
      [keyOf(0, 0)]: 7, // source A1
    });
    expect(computeAutofillTarget(read, box(0, 0, 0, 0), dims)).toEqual(box(0, 1, 0, 0));
  });

  it("returns the source unchanged when no neighbor has data", () => {
    const read = reader({ [keyOf(0, 1)]: "=A1" });
    expect(computeAutofillTarget(read, box(0, 0, 1, 1), dims)).toEqual(box(0, 0, 1, 1));
  });
});
