/**
 * The recents tab bar both BUILDS entity URLs and PARSES them back out of the
 * pathname to decide which tab is active. Neither direction is type-checked
 * against the router, so a URL-shape change breaks the highlight silently —
 * which is exactly what these tests are for.
 */
import { describe, expect, it } from "vitest";

import { buildRecentItem } from "@/__tests__/factories/recent.factory";
import { getActiveRecentKey, recentKeyMatches, recentRoute } from "@/lib/recentRoute";

describe("recentRoute", () => {
  it("addresses an entity inside its guild and initiative", () => {
    const item = buildRecentItem({
      entity_type: "project",
      entity_id: 7,
      guild_id: 3,
      initiative_id: 5,
    });
    expect(recentRoute(item)).toBe("/c/3/i/5/projects/7");
  });

  // Only calendars can be guild-level (an app installs one).
  it("keeps a guild-level entity at its guild route", () => {
    const item = buildRecentItem({
      entity_type: "calendar",
      entity_id: 9,
      guild_id: 3,
      initiative_id: null,
    });
    expect(recentRoute(item)).toBe("/c/3/calendars/9");
  });
});

describe("getActiveRecentKey", () => {
  it("reads guild, initiative, tool and entity out of a nested path", () => {
    expect(getActiveRecentKey("/c/3/i/5/counter-groups/7")).toEqual({
      entityType: "counter_group",
      entityId: 7,
      guildId: 3,
      initiativeId: 5,
    });
  });

  it("still matches when the path continues past the entity", () => {
    expect(getActiveRecentKey("/c/1/i/2/projects/4/tasks/9")).toEqual({
      entityType: "project",
      entityId: 4,
      guildId: 1,
      initiativeId: 2,
    });
  });

  it("reads the guild-level shape with no initiative segment", () => {
    expect(getActiveRecentKey("/c/1/calendars/12")).toEqual({
      entityType: "calendar",
      entityId: 12,
      guildId: 1,
      initiativeId: null,
    });
  });

  it("returns null for a path that names no entity", () => {
    expect(getActiveRecentKey("/c/1/i/2/projects")).toBeNull();
    expect(getActiveRecentKey("/c/1/i/2")).toBeNull();
    expect(getActiveRecentKey("/c/1/settings/users")).toBeNull();
    expect(getActiveRecentKey("/profile")).toBeNull();
    // A tool segment that isn't a tool.
    expect(getActiveRecentKey("/c/1/i/2/widgets/3")).toBeNull();
    // A non-numeric id must not parse as one.
    expect(getActiveRecentKey("/c/1/i/2/projects/gallery")).toBeNull();
  });
});

describe("recentKeyMatches", () => {
  it("matches on guild too, since entity ids collide across guilds", () => {
    const item = buildRecentItem({ entity_type: "project", entity_id: 4, guild_id: 1 });
    expect(recentKeyMatches(getActiveRecentKey("/c/1/i/2/projects/4"), item)).toBe(true);
    expect(recentKeyMatches(getActiveRecentKey("/c/9/i/2/projects/4"), item)).toBe(false);
    expect(recentKeyMatches(null, item)).toBe(false);
  });
});
