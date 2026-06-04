import { describe, expect, it } from "vitest";

import { type CellValue, keyOf } from "./coords";
import { sortSheetByColumn } from "./sort";

/** Build a cell Map from a "r:c" -> value record for terse fixtures. */
const cellMap = (obj: Record<string, CellValue>): Map<string, CellValue> =>
  new Map(Object.entries(obj));

/** Read column ``col`` top-to-bottom from a remapped cell record. */
const column = (cells: Record<string, CellValue>, col: number, rows: number): CellValue[] =>
  Array.from({ length: rows }, (_, r) => cells[keyOf(r, col)] ?? null);

describe("sortSheetByColumn", () => {
  it("sorts numbers ascending and keeps other columns aligned", () => {
    // col 0 = sort key, col 1 = label that must travel with its row.
    const cells = cellMap({
      "0:0": 3,
      "0:1": "c",
      "1:0": 1,
      "1:1": "a",
      "2:0": 2,
      "2:1": "b",
    });
    const result = sortSheetByColumn(cells, {}, {}, { column: 0, direction: "asc" });
    expect(result.changed).toBe(true);
    expect(column(result.cells, 0, 3)).toEqual([1, 2, 3]);
    expect(column(result.cells, 1, 3)).toEqual(["a", "b", "c"]);
  });

  it("sorts descending", () => {
    const cells = cellMap({ "0:0": 1, "1:0": 3, "2:0": 2 });
    const result = sortSheetByColumn(cells, {}, {}, { column: 0, direction: "desc" });
    expect(column(result.cells, 0, 3)).toEqual([3, 2, 1]);
  });

  it("sorts text with natural, case-insensitive ordering", () => {
    const cells = cellMap({ "0:0": "item10", "1:0": "item2", "2:0": "Item1" });
    const result = sortSheetByColumn(cells, {}, {}, { column: 0, direction: "asc" });
    expect(column(result.cells, 0, 3)).toEqual(["Item1", "item2", "item10"]);
  });

  it("orders numbers before text before booleans (Excel precedence)", () => {
    const cells = cellMap({ "0:0": true, "1:0": "x", "2:0": 5 });
    const result = sortSheetByColumn(cells, {}, {}, { column: 0, direction: "asc" });
    expect(column(result.cells, 0, 3)).toEqual([5, "x", true]);
  });

  it("always sinks blanks to the bottom, even descending", () => {
    // Blanks keep their original relative order (null from row 1 before
    // "" from row 3) and their stored value is preserved verbatim.
    const cells = cellMap({ "0:0": 2, "1:0": null, "2:0": 1, "3:0": "" });
    const asc = sortSheetByColumn(cells, {}, {}, { column: 0, direction: "asc" });
    expect(column(asc.cells, 0, 4)).toEqual([1, 2, null, ""]);
    const desc = sortSheetByColumn(cells, {}, {}, { column: 0, direction: "desc" });
    expect(column(desc.cells, 0, 4)).toEqual([2, 1, null, ""]);
  });

  it("is stable for equal keys", () => {
    const cells = cellMap({
      "0:0": 1,
      "0:1": "first",
      "1:0": 1,
      "1:1": "second",
      "2:0": 1,
      "2:1": "third",
    });
    const result = sortSheetByColumn(cells, {}, {}, { column: 0, direction: "asc" });
    expect(column(result.cells, 1, 3)).toEqual(["first", "second", "third"]);
  });

  it("preserves rows above startRow (frozen header) and only sorts below", () => {
    const cells = cellMap({
      "0:0": "Header",
      "1:0": 3,
      "2:0": 1,
      "3:0": 2,
    });
    const result = sortSheetByColumn(
      cells,
      {},
      {},
      {
        column: 0,
        direction: "asc",
        startRow: 1,
      }
    );
    expect(column(result.cells, 0, 4)).toEqual(["Header", 1, 2, 3]);
  });

  it("moves per-cell styles with their row", () => {
    const cells = cellMap({ "0:0": 2, "1:0": 1 });
    const cellStyles = { "0:0": { style: { bold: true } } };
    const result = sortSheetByColumn(cells, cellStyles, {}, { column: 0, direction: "asc" });
    // Row with value 2 moved from row 0 to row 1, so its style follows.
    expect(result.cells[keyOf(1, 0)]).toBe(2);
    expect(result.cellStyles[keyOf(1, 0)]).toEqual({ style: { bold: true } });
    expect(result.cellStyles[keyOf(0, 0)]).toBeUndefined();
  });

  it("moves per-row formatting with its row", () => {
    const cells = cellMap({ "0:0": 2, "1:0": 1 });
    const rowFmt = { "0": { height: 50 } };
    const result = sortSheetByColumn(cells, {}, rowFmt, { column: 0, direction: "asc" });
    expect(result.rows["1"]).toEqual({ height: 50 });
    expect(result.rows["0"]).toBeUndefined();
  });

  it("reports changed=false when already sorted", () => {
    const cells = cellMap({ "0:0": 1, "1:0": 2, "2:0": 3 });
    const result = sortSheetByColumn(cells, {}, {}, { column: 0, direction: "asc" });
    expect(result.changed).toBe(false);
  });

  it("reports changed=false for an empty sheet", () => {
    const result = sortSheetByColumn(cellMap({}), {}, {}, { column: 0, direction: "asc" });
    expect(result.changed).toBe(false);
  });

  it("sorts by a non-zero column", () => {
    const cells = cellMap({
      "0:0": "a",
      "0:1": 3,
      "1:0": "b",
      "1:1": 1,
      "2:0": "c",
      "2:1": 2,
    });
    const result = sortSheetByColumn(cells, {}, {}, { column: 1, direction: "asc" });
    expect(column(result.cells, 1, 3)).toEqual([1, 2, 3]);
    expect(column(result.cells, 0, 3)).toEqual(["b", "c", "a"]);
  });
});
