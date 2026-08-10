import { describe, expect, it } from "vitest";

import {
  formatSheetPrefix,
  MAX_SHEET_NAME_LENGTH,
  needsSheetQuoting,
  newSheetId,
  nextSheetName,
  quoteSheetName,
  sanitizeSheetName,
  sheetNameKey,
  uniqueSheetName,
  unquoteSheetName,
} from "@/lib/spreadsheet/sheets";

describe("sanitizeSheetName", () => {
  it("drops the characters the formula grammar uses as delimiters", () => {
    expect(sanitizeSheetName("Q1/Q2: *plan*?")).toBe("Q1Q2 plan");
    expect(sanitizeSheetName("a[b]c\\d")).toBe("abcd");
  });

  it("collapses whitespace and trims edge quotes", () => {
    expect(sanitizeSheetName("  Q1   Actuals  ")).toBe("Q1 Actuals");
    expect(sanitizeSheetName("'quoted'")).toBe("quoted");
  });

  it("caps at Excel's limit without leaving a trailing space", () => {
    const long = `${"x".repeat(30)} tail`;
    const out = sanitizeSheetName(long);
    expect(out.length).toBeLessThanOrEqual(MAX_SHEET_NAME_LENGTH);
    expect(out).toBe("x".repeat(30));
  });

  it("returns empty when nothing usable is left", () => {
    expect(sanitizeSheetName("   ")).toBe("");
    expect(sanitizeSheetName("///")).toBe("");
  });
});

describe("uniqueSheetName", () => {
  it("returns the name when it's free", () => {
    expect(uniqueSheetName("Data", ["Summary"])).toBe("Data");
  });

  it("de-duplicates case-insensitively — references resolve that way", () => {
    expect(uniqueSheetName("budget", ["BUDGET"])).toBe("budget 2");
    expect(uniqueSheetName("Data", ["Data", "Data 2"])).toBe("Data 3");
  });

  it("keeps the suffixed name inside the length cap", () => {
    const base = "y".repeat(MAX_SHEET_NAME_LENGTH);
    const out = uniqueSheetName(base, [base]);
    expect(out.length).toBeLessThanOrEqual(MAX_SHEET_NAME_LENGTH);
    expect(out.endsWith(" 2")).toBe(true);
  });
});

describe("nextSheetName", () => {
  it("picks the first free Sheet<n>", () => {
    expect(nextSheetName([])).toBe("Sheet1");
    expect(nextSheetName(["Sheet1", "Sheet3"])).toBe("Sheet2");
    expect(nextSheetName(["sheet1", "Sheet2"])).toBe("Sheet3");
  });
});

describe("quoting", () => {
  it("leaves a bare identifier unquoted", () => {
    expect(needsSheetQuoting("Sheet2")).toBe(false);
    expect(quoteSheetName("Sheet2")).toBe("Sheet2");
    expect(formatSheetPrefix("Sheet2")).toBe("Sheet2!");
  });

  it("quotes names with spaces or punctuation", () => {
    expect(quoteSheetName("Q1 Actuals")).toBe("'Q1 Actuals'");
    expect(formatSheetPrefix("Q1 Actuals")).toBe("'Q1 Actuals'!");
    expect(quoteSheetName("2026")).toBe("'2026'");
  });

  it("quotes names that would read as something else", () => {
    // Unquoted, these would parse as a cell reference / a literal.
    expect(needsSheetQuoting("A1")).toBe(true);
    expect(needsSheetQuoting("TRUE")).toBe(true);
    expect(quoteSheetName("A1")).toBe("'A1'");
  });

  it("escapes apostrophes and round-trips", () => {
    expect(quoteSheetName("Bob's Data")).toBe("'Bob''s Data'");
    expect(unquoteSheetName("'Bob''s Data'")).toBe("Bob's Data");
    expect(unquoteSheetName("Sheet2")).toBe("Sheet2");
  });
});

describe("sheetNameKey", () => {
  it("is case- and edge-whitespace-insensitive", () => {
    expect(sheetNameKey(" Data ")).toBe(sheetNameKey("DATA"));
  });
});

describe("newSheetId", () => {
  it("mints distinct ids that survive the formula-safe id charset", () => {
    const ids = new Set(Array.from({ length: 50 }, () => newSheetId()));
    expect(ids.size).toBe(50);
    for (const id of ids) expect(id).toMatch(/^[A-Za-z0-9_-]+$/);
  });
});
