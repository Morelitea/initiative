import { describe, expect, it } from "vitest";

import { formatDate, formatDateTime, parseDateValue } from "@/lib/formatDate";

describe("parseDateValue", () => {
  it("resolves a date-only value to that local calendar day", () => {
    // Asserted in local-time getters so the expectation holds in any timezone —
    // parsed as UTC, this lands on Mar 1 anywhere west of Greenwich.
    const parsed = parseDateValue("2026-03-02");

    expect(parsed?.getFullYear()).toBe(2026);
    expect(parsed?.getMonth()).toBe(2);
    expect(parsed?.getDate()).toBe(2);
  });

  it("returns null for missing or unparsable input", () => {
    expect(parseDateValue(null)).toBeNull();
    expect(parseDateValue("")).toBeNull();
    expect(parseDateValue("not a date")).toBeNull();
  });
});

describe("formatDate", () => {
  it("renders a date-only value as the day it names", () => {
    expect(formatDate("2026-03-02")).toBe("Mar 2, 2026");
  });

  it("returns an empty string for missing or unparsable input", () => {
    expect(formatDate(null)).toBe("");
    expect(formatDate("nope")).toBe("");
  });

  it("keeps the time for a timestamp", () => {
    expect(formatDateTime("2026-03-02T15:30:00Z")).toMatch(/2026/);
  });
});
