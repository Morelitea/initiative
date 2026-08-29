import { describe, expect, it } from "vitest";

import { DARK_TEXT, LIGHT_TEXT, readableTextColor, relativeLuminance } from "./contrastColor";

describe("readableTextColor", () => {
  it("puts light text on a dark fill and dark text on a light one", () => {
    expect(readableTextColor("#000000")).toBe(LIGHT_TEXT);
    expect(readableTextColor("#ffffff")).toBe(DARK_TEXT);
    expect(readableTextColor("#2563eb")).toBe(LIGHT_TEXT);
    expect(readableTextColor("#f5f0e8")).toBe(DARK_TEXT);
  });

  it("decides by contrast ratio, not by a lightness guess", () => {
    // A mid-tone teal is light enough that a naive threshold flips, but black
    // genuinely reads better on it — the ratio says so.
    const luminance = relativeLuminance("#2a9d8f");
    expect(luminance).not.toBeNull();
    const white = 1.05 / ((luminance as number) + 0.05);
    const black = ((luminance as number) + 0.05) / 0.05;
    expect(readableTextColor("#2a9d8f")).toBe(black > white ? DARK_TEXT : LIGHT_TEXT);
  });

  it("reads the short and alpha-bearing forms the picker can emit", () => {
    expect(readableTextColor("#fff")).toBe(DARK_TEXT);
    expect(readableTextColor("#000000ff")).toBe(LIGHT_TEXT);
    expect(readableTextColor("#2563EB")).toBe(LIGHT_TEXT);
  });

  it("falls back to light text rather than throwing on nonsense", () => {
    expect(readableTextColor("rebeccapurple")).toBe(LIGHT_TEXT);
    expect(readableTextColor("")).toBe(LIGHT_TEXT);
    expect(relativeLuminance("nope")).toBeNull();
  });
});
