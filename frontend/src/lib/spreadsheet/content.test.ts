import { describe, expect, it } from "vitest";

import {
  DEFAULT_COLS,
  DEFAULT_ROWS,
  emptySpreadsheetContent,
  parseSpreadsheetContent,
  SPREADSHEET_SCHEMA_VERSION,
} from "@/lib/spreadsheet/content";

describe("parseSpreadsheetContent — upcast", () => {
  it("reads a v1 document as the workbook's single sheet", () => {
    const out = parseSpreadsheetContent({
      schema_version: 1,
      kind: "spreadsheet",
      dimensions: { rows: 100, cols: 26 },
      cells: { "0:0": "kept" },
    });
    expect(out.schema_version).toBe(SPREADSHEET_SCHEMA_VERSION);
    expect(out.sheets).toHaveLength(1);
    expect(out.sheets[0].name).toBe("Sheet1");
    expect(out.sheets[0].cells).toEqual({ "0:0": "kept" });
  });

  it("carries a v2 document's formatting onto that sheet", () => {
    const out = parseSpreadsheetContent({
      schema_version: 2,
      kind: "spreadsheet",
      cells: { "0:0": 1 },
      columns: { "0": { width: 200 } },
      cellStyles: { "0:0": { style: { bold: true } } },
      frozen: { rows: 1, cols: 1 },
    });
    expect(out.sheets[0].columns).toEqual({ "0": { width: 200 } });
    expect(out.sheets[0].cellStyles).toEqual({ "0:0": { style: { bold: true } } });
    expect(out.sheets[0].frozen).toEqual({ rows: 1, cols: 1 });
  });

  it("produces a usable workbook from junk", () => {
    for (const junk of [null, undefined, 42, "nope", []]) {
      const out = parseSpreadsheetContent(junk);
      expect(out.sheets).toHaveLength(1);
      expect(out.sheets[0].dimensions).toEqual({ rows: DEFAULT_ROWS, cols: DEFAULT_COLS });
    }
  });
});

describe("parseSpreadsheetContent — v3", () => {
  it("keeps sheets, order, and per-sheet content", () => {
    const out = parseSpreadsheetContent({
      schema_version: 3,
      kind: "spreadsheet",
      sheets: [
        { id: "s1", name: "Summary", cells: { "0:0": "=Data!A1" } },
        { id: "sx", name: "Data", cells: { "0:0": 5 } },
      ],
    });
    expect(out.sheets.map((s) => s.name)).toEqual(["Summary", "Data"]);
    expect(out.sheets.map((s) => s.id)).toEqual(["s1", "sx"]);
    expect(out.sheets[0].cells).toEqual({ "0:0": "=Data!A1" });
  });

  it("de-duplicates names case-insensitively", () => {
    const out = parseSpreadsheetContent({
      schema_version: 3,
      sheets: [
        { id: "a", name: "Budget" },
        { id: "b", name: "BUDGET" },
      ],
    });
    expect(out.sheets.map((s) => s.name)).toEqual(["Budget", "BUDGET 2"]);
  });

  it("re-issues a duplicated id so two tabs never share one container", () => {
    const out = parseSpreadsheetContent({
      schema_version: 3,
      sheets: [
        { id: "same", name: "One" },
        { id: "same", name: "Two" },
      ],
    });
    expect(new Set(out.sheets.map((s) => s.id)).size).toBe(2);
  });

  it("names an unnamed sheet by position and repairs an unusable one", () => {
    const out = parseSpreadsheetContent({
      schema_version: 3,
      sheets: [{ id: "a" }, { id: "b", name: "  ///  " }],
    });
    expect(out.sheets.map((s) => s.name)).toEqual(["Sheet1", "Sheet2"]);
  });

  it("falls back to the top level when sheets is empty or not a list", () => {
    expect(parseSpreadsheetContent({ schema_version: 3, sheets: [] }).sheets).toHaveLength(1);
    const notAList = parseSpreadsheetContent({ sheets: {}, cells: { "0:0": "x" } });
    expect(notAList.sheets[0].cells).toEqual({ "0:0": "x" });
  });

  it("grows a sheet's canvas to cover its furthest cell", () => {
    const out = parseSpreadsheetContent({
      schema_version: 3,
      sheets: [{ id: "a", name: "Big", cells: { "499:2": "far" } }],
    });
    expect(out.sheets[0].dimensions.rows).toBe(500);
  });

  it("drops non-scalar cells and canonicalizes leading-zero keys", () => {
    const out = parseSpreadsheetContent({
      schema_version: 3,
      sheets: [{ id: "a", name: "S", cells: { "01:02": "x", "0:0": { nested: 1 }, "1:1": "" } }],
    });
    expect(out.sheets[0].cells).toEqual({ "1:2": "x" });
  });
});

describe("emptySpreadsheetContent", () => {
  it("is a one-sheet workbook at the default canvas size", () => {
    const out = emptySpreadsheetContent();
    expect(out.sheets).toHaveLength(1);
    expect(out.sheets[0].name).toBe("Sheet1");
    expect(out.sheets[0].cells).toEqual({});
  });
});
