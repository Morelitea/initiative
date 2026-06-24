import { afterEach, beforeEach, describe, expect, it } from "vitest";

import {
  invalidateAllInitiatives,
  invalidateAllTasks,
  invalidateNotifications,
  setInvalidationGuild,
} from "@/api/query-keys";
import { queryClient } from "@/lib/queryClient";

/** Seed a query so it exists in the cache, then report whether it got invalidated. */
const seed = (key: readonly unknown[]) => {
  queryClient.setQueryData(key, { seeded: true });
  return () => queryClient.getQueryState(key)?.isInvalidated ?? false;
};

describe("query-keys guild scoping", () => {
  beforeEach(() => {
    queryClient.clear();
    setInvalidationGuild(null);
  });

  afterEach(() => {
    queryClient.clear();
    setInvalidationGuild(null);
  });

  it("invalidates only the active guild's queries", async () => {
    const activeGuild = seed(["/api/v1/g/5/tasks/"]);
    const otherGuild = seed(["/api/v1/g/7/tasks/"]);

    setInvalidationGuild(5);
    await invalidateAllTasks();

    expect(activeGuild()).toBe(true);
    expect(otherGuild()).toBe(false);
  });

  it("still invalidates the cross-guild /me aggregate", async () => {
    const guildScoped = seed(["/api/v1/g/5/tasks/"]);
    const meAggregate = seed(["/api/v1/me/tasks"]);

    setInvalidationGuild(5);
    await invalidateAllTasks();

    expect(guildScoped()).toBe(true);
    expect(meAggregate()).toBe(true);
  });

  it("falls back to plain matching when no active guild is set", async () => {
    const guildA = seed(["/api/v1/g/5/tasks/"]);
    const guildB = seed(["/api/v1/g/7/tasks/"]);

    // No setInvalidationGuild call (personal mode / pre-mount): scoping is skipped.
    await invalidateAllTasks();

    expect(guildA()).toBe(true);
    expect(guildB()).toBe(true);
  });

  describe("boundaries do not cross", () => {
    it("guild invalidation never touches personal / platform keys", async () => {
      const guildScoped = seed(["/api/v1/g/5/initiatives/"]);
      const meTasks = seed(["/api/v1/me/tasks"]);
      const notifications = seed(["/api/v1/notifications/"]);
      const recents = seed(["/api/v1/recents/"]);

      setInvalidationGuild(5);
      await invalidateAllInitiatives();

      expect(guildScoped()).toBe(true);
      expect(meTasks()).toBe(false);
      expect(notifications()).toBe(false);
      expect(recents()).toBe(false);
    });

    it("personal invalidation never touches guild keys", async () => {
      const notifications = seed(["/api/v1/notifications/"]);
      const guildTasks = seed(["/api/v1/g/5/tasks/"]);

      setInvalidationGuild(5);
      await invalidateNotifications();

      expect(notifications()).toBe(true);
      expect(guildTasks()).toBe(false);
    });
  });
});
