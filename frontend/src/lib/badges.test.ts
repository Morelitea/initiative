import { describe, expect, it } from "vitest";

import { BadgeKind, BadgeTone, SearchEntityType } from "@/api/generated/initiativeAPI.schemas";
import {
  BADGE_KINDS,
  BADGE_TONE_CLASSES,
  badgeAspect,
  badgeDisplay,
  badgeEntityType,
  badgeRef,
} from "@/lib/badges";

const iso = (date: string) => new Date(date).toISOString();
const formatDate = () => "formatted";

describe("what a badge is about", () => {
  it("takes its kinds from the server rather than a list of its own", () => {
    expect(BADGE_KINDS).toEqual(Object.values(BadgeKind));
    expect(BADGE_KINDS).toContain(BadgeKind["task:status"]);
  });

  it("splits a pair into the thing and the fact", () => {
    expect(badgeEntityType(BadgeKind["task:status"])).toBe(SearchEntityType.task);
    expect(badgeAspect(BadgeKind["task:status"])).toBe("status");
    expect(badgeEntityType(BadgeKind["calendar_event:when"])).toBe(SearchEntityType.calendar_event);
  });

  it("writes the reference the document stores", () => {
    expect(badgeRef(BadgeKind["task:status"], 12)).toBe("task:12:status");
    expect(badgeRef(BadgeKind["calendar_event:when"], 4)).toBe("calendar_event:4:when");
  });

  it("has a look for every tone the server can send", () => {
    for (const tone of Object.values(BadgeTone)) {
      expect(BADGE_TONE_CLASSES[tone]).toBeTruthy();
    }
  });

  it("colours from theme tokens, so a chip follows the reader's theme", () => {
    for (const classes of Object.values(BADGE_TONE_CLASSES)) {
      expect(classes).not.toMatch(/\bdark:/);
      // A fixed palette shade would not move with the theme.
      expect(classes).not.toMatch(/-\d{3}\b/);
    }
  });
});

describe("what a chip shows", () => {
  it("falls back to the stored label when the thing cannot be read", () => {
    const display = badgeDisplay("Ship the release", undefined, formatDate);
    expect(display.text).toBe("Ship the release");
    expect(display.className).toBe(BADGE_TONE_CLASSES[BadgeTone.muted]);
  });

  it("shows the live state over the label the document stored", () => {
    const display = badgeDisplay(
      "Ship the release",
      { ref: "task:1:status", kind: BadgeKind["task:status"], text: "Done", tone: BadgeTone.good },
      formatDate
    );
    expect(display.text).toBe("Done");
    expect(display.className).toBe(BADGE_TONE_CLASSES[BadgeTone.good]);
  });

  it("lets the thing's own colour beat the tone", () => {
    const display = badgeDisplay(
      "x",
      {
        ref: "task:1:status",
        kind: BadgeKind["task:status"],
        text: "Blocked",
        tone: BadgeTone.neutral,
        color: "#FF00AA",
      },
      formatDate
    );
    expect(display.color).toBe("#FF00AA");
  });

  it("formats a date in the reader's locale rather than showing the server's", () => {
    const display = badgeDisplay(
      "x",
      {
        ref: "task:1:due",
        kind: BadgeKind["task:due"],
        text: "2026-09-12",
        tone: BadgeTone.neutral,
        date: iso("2026-09-12T10:00:00Z"),
      },
      formatDate
    );
    expect(display.text).toBe("formatted");
  });
});
