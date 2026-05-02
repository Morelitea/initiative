import { describe, expect, it } from "vitest";

import { boundingBox, colIndexToLetter, keyOf, letterToColIndex, parseKey } from "./coords";

describe("colIndexToLetter / letterToColIndex", () => {
  it("round-trips single-letter columns", () => {
    expect(colIndexToLetter(0)).toBe("A");
    expect(colIndexToLetter(25)).toBe("Z");
    expect(letterToColIndex("A")).toBe(0);
    expect(letterToColIndex("Z")).toBe(25);
  });

  it("round-trips double-letter columns at the boundary", () => {
    expect(colIndexToLetter(26)).toBe("AA");
    expect(colIndexToLetter(51)).toBe("AZ");
    expect(colIndexToLetter(52)).toBe("BA");
    expect(colIndexToLetter(701)).toBe("ZZ");
    expect(letterToColIndex("AA")).toBe(26);
    expect(letterToColIndex("AZ")).toBe(51);
    expect(letterToColIndex("ZZ")).toBe(701);
  });

  it("handles triple-letter columns", () => {
    expect(colIndexToLetter(702)).toBe("AAA");
    expect(letterToColIndex("AAA")).toBe(702);
  });

  it("is case-insensitive on parse", () => {
    expect(letterToColIndex("aa")).toBe(26);
    expect(letterToColIndex("Aa")).toBe(26);
  });

  it("returns -1 for invalid letter input", () => {
    expect(letterToColIndex("")).toBe(-1);
    expect(letterToColIndex("A1")).toBe(-1);
    expect(letterToColIndex("@")).toBe(-1);
  });

  it("returns empty string for invalid index input", () => {
    expect(colIndexToLetter(-1)).toBe("");
    expect(colIndexToLetter(0.5)).toBe("");
  });
});

describe("keyOf / parseKey", () => {
  it("round-trips r:c keys", () => {
    expect(keyOf(0, 0)).toBe("0:0");
    expect(keyOf(7, 12)).toBe("7:12");
    expect(parseKey("7:12")).toEqual([7, 12]);
  });

  it("rejects malformed keys", () => {
    expect(parseKey("A1")).toBeNull();
    expect(parseKey("0,0")).toBeNull();
    expect(parseKey("0")).toBeNull();
    expect(parseKey("")).toBeNull();
  });
});

describe("boundingBox", () => {
  it("returns 0×0 for an empty map", () => {
    expect(boundingBox({})).toEqual({ rows: 0, cols: 0 });
    expect(boundingBox(new Map())).toEqual({ rows: 0, cols: 0 });
  });

  it("returns max + 1 dimensions for a populated map", () => {
    const cells = { "0:0": "a", "2:5": 42, "1:7": true };
    expect(boundingBox(cells)).toEqual({ rows: 3, cols: 8 });
  });

  it("ignores malformed keys", () => {
    const cells = { "0:0": "a", garbage: 1, "5:5": 2 } as Record<string, never>;
    expect(boundingBox(cells)).toEqual({ rows: 6, cols: 6 });
  });

  it("works on a Map<string, CellValue>", () => {
    const map = new Map<string, string | number>([
      ["0:0", "a"],
      ["3:1", 99],
    ]);
    expect(boundingBox(map)).toEqual({ rows: 4, cols: 2 });
  });
});
