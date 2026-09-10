import { describe, expect, it } from "vitest";

import type { CellValue } from "./coords";
import { coerceScalar } from "./csv";
import { findInCells, replaceAllInCells, replaceInValue } from "./find";

const sheet = (obj: Record<string, CellValue>) => new Map(Object.entries(obj));
const loose = { matchCase: false, wholeCell: false };

describe("findInCells", () => {
  it("finds a substring, ignoring case by default", () => {
    const found = findInCells(sheet({ "0:0": "Total cost", "1:0": "other" }), "total", loose);
    expect(found).toEqual([{ row: 0, col: 0 }]);
  });

  it("respects match case", () => {
    const cells = sheet({ "0:0": "Total", "1:0": "total" });
    expect(findInCells(cells, "total", { matchCase: true, wholeCell: false })).toEqual([
      { row: 1, col: 0 },
    ]);
  });

  it("matches the whole cell when asked", () => {
    const cells = sheet({ "0:0": "cost", "1:0": "cost of goods" });
    expect(findInCells(cells, "cost", { matchCase: false, wholeCell: true })).toEqual([
      { row: 0, col: 0 },
    ]);
  });

  it("searches the stored text, so a formula matches its own source", () => {
    const cells = sheet({ "0:0": "=SUM(A2:A9)" });
    expect(findInCells(cells, "sum(", loose)).toEqual([{ row: 0, col: 0 }]);
  });

  it("matches numbers and booleans by their text", () => {
    const cells = sheet({ "0:0": 1234, "1:0": true });
    expect(findInCells(cells, "23", loose)).toEqual([{ row: 0, col: 0 }]);
    expect(findInCells(cells, "true", loose)).toEqual([{ row: 1, col: 0 }]);
  });

  it("returns matches in reading order", () => {
    const cells = sheet({ "2:0": "x", "0:5": "x", "0:1": "x", "1:9": "x" });
    expect(findInCells(cells, "x", loose)).toEqual([
      { row: 0, col: 1 },
      { row: 0, col: 5 },
      { row: 1, col: 9 },
      { row: 2, col: 0 },
    ]);
  });

  it("treats query characters literally", () => {
    const cells = sheet({ "0:0": "a.c", "1:0": "abc" });
    expect(findInCells(cells, "a.c", loose)).toEqual([{ row: 0, col: 0 }]);
  });

  it("finds nothing for an empty query", () => {
    expect(findInCells(sheet({ "0:0": "anything" }), "", loose)).toEqual([]);
  });
});

describe("replaceInValue", () => {
  it("is null when the cell doesn't match", () => {
    expect(replaceInValue("hello", "xyz", "!", loose)).toBeNull();
  });

  it("replaces every occurrence in the cell", () => {
    expect(replaceInValue("a-a-a", "a", "b", loose)).toBe("b-b-b");
  });

  it("replaces case-insensitively but writes the replacement as typed", () => {
    expect(replaceInValue("Total total", "total", "sum", loose)).toBe("sum sum");
  });

  it("replaces the whole cell when asked", () => {
    expect(
      replaceInValue("cost of goods", "COST OF GOODS", "x", {
        matchCase: false,
        wholeCell: true,
      })
    ).toBe("x");
  });

  it("leaves a non-matching part of the text alone", () => {
    expect(replaceInValue("=SUM(A1:A9)", "A1", "B1", loose)).toBe("=SUM(B1:A9)");
  });
});

describe("replaceAllInCells", () => {
  it("writes only the cells that changed", () => {
    const cells = sheet({ "0:0": "cost", "0:1": "other", "1:0": "cost centre" });
    const writes = replaceAllInCells(cells, "cost", "price", loose, coerceScalar);
    expect(writes).toEqual({ "0:0": "price", "1:0": "price centre" });
  });

  it("re-coerces a result that reads as a number", () => {
    const cells = sheet({ "0:0": "12x" });
    const writes = replaceAllInCells(cells, "x", "", loose, coerceScalar);
    expect(writes["0:0"]).toBe(12);
  });

  it("clears a cell replaced down to nothing", () => {
    const cells = sheet({ "0:0": "x" });
    expect(replaceAllInCells(cells, "x", "", loose, coerceScalar)["0:0"]).toBeNull();
  });

  it("does nothing for an empty query", () => {
    expect(replaceAllInCells(sheet({ "0:0": "a" }), "", "b", loose, coerceScalar)).toEqual({});
  });
});
