import { describe, expect, it } from "vitest";

import { cellsToCsv, coerceScalar, csvToCells, detectClipboardDelimiter, offsetCells } from "./csv";

describe("cellsToCsv / csvToCells round-trip", () => {
  it("round-trips a small grid", () => {
    const cells = {
      "0:0": "Date",
      "0:1": "Amount",
      "1:0": "2026-05-01",
      "1:1": 42.5,
      "2:1": true,
    };
    const csv = cellsToCsv(cells);
    const parsed = csvToCells(csv);
    // Numeric / boolean values get re-coerced from their string form.
    expect(parsed.cells).toEqual({
      "0:0": "Date",
      "0:1": "Amount",
      "1:0": "2026-05-01",
      "1:1": 42.5,
      "2:1": true,
    });
  });

  it("preserves embedded commas via quoting", () => {
    const cells = { "0:0": "hello, world", "0:1": "ok" };
    const csv = cellsToCsv(cells);
    expect(csv).toContain('"hello, world"');
    expect(csvToCells(csv).cells).toEqual({ "0:0": "hello, world", "0:1": "ok" });
  });

  it("preserves embedded newlines via quoting", () => {
    const cells = { "0:0": "line one\nline two" };
    const csv = cellsToCsv(cells);
    expect(csvToCells(csv).cells).toEqual({ "0:0": "line one\nline two" });
  });

  it("returns empty string for an empty cell map", () => {
    expect(cellsToCsv({})).toBe("");
  });

  it("emits empty fields inside the bounding box for missing cells", () => {
    const csv = cellsToCsv({ "0:0": "a", "1:1": "b" });
    // Bounding box is 2x2: A1=a, B1=empty, A2=empty, B2=b.
    expect(csv).toBe("a,\n,b");
  });
});

describe("coerceScalar", () => {
  it("coerces numeric-looking strings to numbers", () => {
    expect(coerceScalar("42")).toBe(42);
    expect(coerceScalar("-3.5")).toBe(-3.5);
    expect(coerceScalar("1e3")).toBe(1000);
  });

  it("preserves leading zeros (likely IDs / phone numbers)", () => {
    expect(coerceScalar("0123")).toBe("0123");
    expect(coerceScalar("00")).toBe("00");
  });

  it("trims surrounding whitespace from leading-zero strings", () => {
    expect(coerceScalar(" 0123")).toBe("0123");
    expect(coerceScalar("0123 ")).toBe("0123");
    expect(coerceScalar("\t00\n")).toBe("00");
  });

  it("coerces true / false case-insensitively", () => {
    expect(coerceScalar("true")).toBe(true);
    expect(coerceScalar("FALSE")).toBe(false);
    expect(coerceScalar("TruE")).toBe(true);
  });

  it("leaves other strings alone", () => {
    expect(coerceScalar("hello")).toBe("hello");
    expect(coerceScalar("2026-05-01")).toBe("2026-05-01");
  });
});

describe("detectClipboardDelimiter", () => {
  it("prefers tab when present (Excel/Sheets paste shape)", () => {
    expect(detectClipboardDelimiter("a\tb")).toBe("\t");
    expect(detectClipboardDelimiter("a\tb,c")).toBe("\t");
  });

  it("falls back to comma when no tab is present", () => {
    expect(detectClipboardDelimiter("a,b")).toBe(",");
  });

  it("returns empty string for plain text (papaparse will sniff)", () => {
    expect(detectClipboardDelimiter("just text")).toBe("");
  });
});

describe("offsetCells", () => {
  it("shifts a cell map by the given origin", () => {
    const result = offsetCells({ "0:0": "a", "0:1": "b", "1:0": "c" }, 5, 7);
    expect(result).toEqual({ "5:7": "a", "5:8": "b", "6:7": "c" });
  });

  it("ignores malformed keys", () => {
    const result = offsetCells({ "0:0": "a", garbage: "x" } as Record<string, never>, 1, 1);
    expect(result).toEqual({ "1:1": "a" });
  });
});
