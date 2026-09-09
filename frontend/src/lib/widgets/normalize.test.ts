/**
 * From what an endpoint answered to what a widget reads.
 *
 * Two producers, one envelope: a statement's columns arrive already typed, a
 * spreadsheet range's are read off its values. What is asserted here is that
 * both come out the same shape and that neither can hand a widget a row it
 * would index past the end of.
 */
import { describe, expect, it } from "vitest";

import { emptyDataFor, normalizeQueryRows, normalizeSheetRange } from "./normalize";

describe("normalizeSheetRange", () => {
  const doc = (cells: Record<string, unknown>, name = "Sheet1") =>
    ({ content: { sheets: [{ id: "s1", name, cells }] } }) as never;

  it("extracts an A1 range in row-major order", () => {
    const range = normalizeSheetRange(
      doc({ "0:0": "Stage", "0:1": "Count", "1:0": "Leads", "1:1": 100 }),
      "Sheet1",
      "A1:B2"
    );
    expect(range).toEqual({
      columns: [
        { name: "Stage", type: "text" },
        { name: "Count", type: "number" },
      ],
      rows: [["Leads", 100]],
    });
  });

  it("treats an all-text first row as headers only when rows follow", () => {
    const range = normalizeSheetRange(doc({ "0:0": "Only", "0:1": "Headers" }), null, "A1:B1");
    expect(range?.columns.map((column) => column.name)).toEqual(["Column 1", "Column 2"]);
    expect(range?.rows).toEqual([["Only", "Headers"]]);
  });

  it("nulls a cell holding anything that is not a scalar", () => {
    const range = normalizeSheetRange(doc({ "0:0": { nested: true } }), null, "A1");
    expect(range?.rows).toEqual([[null]]);
  });

  it("returns null for an unusable binding rather than throwing", () => {
    expect(normalizeSheetRange(doc({}), "Nope", "A1")).toBeNull();
    expect(normalizeSheetRange(doc({}), "Sheet1", "not-a-range")).toBeNull();
    expect(normalizeSheetRange({ content: null } as never, null, "A1")).toBeNull();
  });
});

describe("normalizeQueryRows", () => {
  const columns = [
    { name: "stage", type: "text" as const },
    { name: "tasks", type: "number" as const },
  ];

  it("keeps rows positional against the described columns", () => {
    expect(normalizeQueryRows(columns, [["Backlog", 4]]).rows).toEqual([["Backlog", 4]]);
  });

  it("holds a row to the described width", () => {
    // Longer is cut, shorter is padded, so a widget indexing by position can
    // never read past the end of a row.
    const { rows } = normalizeQueryRows(columns, [["a", 1, "extra"], ["b"]]);
    expect(rows).toEqual([
      ["a", 1],
      ["b", null],
    ]);
  });

  it("carries scalars as themselves and nulls anything else", () => {
    const mixed = [
      { name: "n", type: "number" as const },
      { name: "b", type: "boolean" as const },
      { name: "o", type: "text" as const },
    ];
    expect(normalizeQueryRows(mixed, [[2, false, { nested: true }]]).rows).toEqual([
      [2, false, null],
    ]);
  });

  it("reports no rows for a statement that returned none", () => {
    expect(normalizeQueryRows(columns, []).rows).toEqual([]);
  });
});

describe("emptyDataFor", () => {
  it("gives a tabular binding an empty tabular envelope", () => {
    for (const source of ["query", "sheet_range"] as const) {
      expect(emptyDataFor(source)).toEqual({ source: "rows", columns: [], rows: [] });
    }
  });

  it("gives an app binding its own empty envelope", () => {
    expect(emptyDataFor("app")).toEqual({ source: "app", rows: [], values: {} });
  });
});
