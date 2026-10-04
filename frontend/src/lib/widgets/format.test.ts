import { describe, expect, it } from "vitest";

import { formatTimeBucket } from "./format";

describe("formatTimeBucket", () => {
  const at = (iso: string) => Date.parse(`${iso}T00:00:00Z`);

  it("labels each grain the way a reader names it", () => {
    expect(formatTimeBucket(at("2026-03-05"), "day", { locale: "en-US" })).toBe("Mar 5");
    expect(formatTimeBucket(at("2026-03-02"), "week", { locale: "en-US" })).toBe("Mar 2");
    expect(formatTimeBucket(at("2026-03-01"), "month", { locale: "en-US" })).toBe("Mar 2026");
    expect(formatTimeBucket(at("2026-04-01"), "quarter")).toBe("Q2 2026");
    expect(formatTimeBucket(at("2026-01-01"), "year")).toBe("2026");
  });

  it("reads the moment in UTC, so midnight is never the day before", () => {
    expect(formatTimeBucket(at("2026-01-01"), "month", { locale: "en-US" })).toBe("Jan 2026");
  });

  it("passes a label that is not a moment through", () => {
    expect(formatTimeBucket("Other", "month")).toBe("Other");
  });
});
