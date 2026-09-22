import { afterEach, describe, expect, it } from "vitest";

import { formatDateTime } from "@/lib/formatDate";
import {
  dateTimePattern,
  formatClockSlot,
  formatCompactTime,
  formatHourLabel,
  hour12Option,
  isHour12,
  notifyTimeFormat,
  parseTimeFormat,
  resetTimeFormat,
  setTimeFormat,
  subscribeTimeFormat,
  timePattern,
  writeTimeFormat,
} from "@/lib/timeFormat";

afterEach(() => {
  resetTimeFormat();
});

describe("parseTimeFormat", () => {
  it("keeps the three answers the app knows", () => {
    expect(parseTimeFormat("system")).toBe("system");
    expect(parseTimeFormat("12")).toBe("12");
    expect(parseTimeFormat("24")).toBe("24");
  });

  it("falls back to system for anything else", () => {
    // An older client, a hand-edited row, or a field that isn't there yet all
    // arrive here, and none of them should force a convention on the reader.
    expect(parseTimeFormat("48")).toBe("system");
    expect(parseTimeFormat(undefined)).toBe("system");
    expect(parseTimeFormat(null)).toBe("system");
  });
});

describe("hour12Option", () => {
  it("leaves the locale alone on system", () => {
    expect(hour12Option()).toBeUndefined();
  });

  it("states the convention once one is picked", () => {
    setTimeFormat("12");
    expect(hour12Option()).toBe(true);
    setTimeFormat("24");
    expect(hour12Option()).toBe(false);
  });
});

describe("isHour12", () => {
  it("answers definitely once a convention is picked", () => {
    setTimeFormat("24");
    expect(isHour12()).toBe(false);
    setTimeFormat("12");
    expect(isHour12()).toBe(true);
  });

  it("asks the runtime on system", () => {
    // The test runtime is en-US, which is a 12-hour locale.
    expect(isHour12()).toBe(true);
  });
});

describe("patterns", () => {
  it("switches the date-fns time pattern", () => {
    setTimeFormat("12");
    expect(timePattern()).toBe("h:mm a");
    expect(dateTimePattern("PP")).toBe("PP h:mm a");

    setTimeFormat("24");
    expect(timePattern()).toBe("HH:mm");
    expect(dateTimePattern("PP")).toBe("PP HH:mm");
  });

  it("keeps seconds when asked for them", () => {
    setTimeFormat("12");
    expect(timePattern({ seconds: true })).toBe("h:mm:ss a");
    setTimeFormat("24");
    expect(dateTimePattern("PP", { seconds: true })).toBe("PP HH:mm:ss");
  });
});

describe("formatClockSlot", () => {
  it("renders a half-hour slot on each clock", () => {
    setTimeFormat("12");
    expect(formatClockSlot("00:00")).toBe("12:00 AM");
    expect(formatClockSlot("09:30")).toBe("9:30 AM");
    expect(formatClockSlot("13:30")).toBe("1:30 PM");

    setTimeFormat("24");
    expect(formatClockSlot("00:00")).toBe("00:00");
    expect(formatClockSlot("09:30")).toBe("09:30");
    expect(formatClockSlot("13:30")).toBe("13:30");
  });

  it("hands back anything that isn't a slot", () => {
    expect(formatClockSlot("not a time")).toBe("not a time");
  });
});

describe("formatHourLabel", () => {
  it("renders a gutter hour on each clock", () => {
    setTimeFormat("12");
    expect([0, 9, 12, 15].map(formatHourLabel)).toEqual(["12am", "9am", "12pm", "3pm"]);

    setTimeFormat("24");
    expect([0, 9, 12, 15].map(formatHourLabel)).toEqual(["00", "09", "12", "15"]);
  });
});

describe("formatCompactTime", () => {
  const at = (hours: number, minutes: number) => new Date(2026, 0, 15, hours, minutes);

  it("drops the minutes on the hour, in 12-hour", () => {
    setTimeFormat("12");
    expect(formatCompactTime(at(9, 0))).toBe("9am");
    expect(formatCompactTime(at(9, 30))).toBe("9:30am");
    expect(formatCompactTime(at(13, 5))).toBe("1:05pm");
  });

  it("always shows both parts in 24-hour, so widths line up", () => {
    setTimeFormat("24");
    expect(formatCompactTime(at(9, 0))).toBe("09:00");
    expect(formatCompactTime(at(13, 5))).toBe("13:05");
  });
});

describe("writeTimeFormat", () => {
  it("takes effect for a formatter without notifying anybody", () => {
    let calls = 0;
    const unsubscribe = subscribeTimeFormat(() => {
      calls += 1;
    });

    expect(writeTimeFormat("24")).toBe(true);
    expect(isHour12()).toBe(false);
    expect(calls).toBe(0);

    // Repeating the same answer is a no-op, which is what makes it safe to
    // call on every render of the root.
    expect(writeTimeFormat("24")).toBe(false);

    notifyTimeFormat();
    expect(calls).toBe(1);
    unsubscribe();
  });
});

describe("subscribeTimeFormat", () => {
  it("notifies on a change and not on a repeat", () => {
    let calls = 0;
    const unsubscribe = subscribeTimeFormat(() => {
      calls += 1;
    });

    setTimeFormat("24");
    setTimeFormat("24");
    expect(calls).toBe(1);

    unsubscribe();
    setTimeFormat("12");
    expect(calls).toBe(1);
  });
});

describe("formatDateTime", () => {
  it("follows the preference", () => {
    const value = "2026-08-03T21:15:00Z";

    setTimeFormat("12");
    expect(formatDateTime(value)).toMatch(/\b(AM|PM)\b/);

    setTimeFormat("24");
    expect(formatDateTime(value)).not.toMatch(/\b(AM|PM)\b/);
  });

  it("renders a date-only value's midnight on the picked clock", () => {
    setTimeFormat("24");
    expect(formatDateTime("2026-08-03")).toBe("Aug 3, 2026, 00:00");

    setTimeFormat("12");
    expect(formatDateTime("2026-08-03")).toBe("Aug 3, 2026, 12:00 AM");
  });
});
