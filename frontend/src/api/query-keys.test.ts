import { afterEach, beforeEach, describe, expect, it } from "vitest";

import {
  invalidateAllAISettings,
  invalidateAllInitiatives,
  invalidateAllTasks,
  invalidateGuildMembers,
  invalidateNotifications,
  patchCachedPost,
  resetGuildScopedQueries,
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

    // The guild member roster is guild-scoped (`/api/v1/g/{id}/users/`) even though
    // its mutations go through the platform `/api/v1/guilds/...` path — a role change
    // must refresh the active guild's roster without a manual reload.
    it("guild member invalidation hits the active guild roster only", async () => {
      const activeRoster = seed(["/api/v1/g/5/users/"]);
      const otherRoster = seed(["/api/v1/g/7/users/"]);

      setInvalidationGuild(5);
      await invalidateGuildMembers();

      expect(activeRoster()).toBe(true);
      expect(otherRoster()).toBe(false);
    });

    // Spanning helper: reaches platform AI (personal) AND the active guild's AI
    // settings, but still never another guild's.
    it("all-AI-settings spans both families without crossing guilds", async () => {
      const platform = seed(["/api/v1/settings/ai/platform"]);
      const guildAI = seed(["/api/v1/g/5/settings/ai/resolved"]);
      const otherGuildAI = seed(["/api/v1/g/7/settings/ai/resolved"]);

      setInvalidationGuild(5);
      await invalidateAllAISettings();

      expect(platform()).toBe(true);
      expect(guildAI()).toBe(true);
      expect(otherGuildAI()).toBe(false);
    });
  });

  describe("guild switch", () => {
    // Reset (unlike invalidate) drops the data, so a surviving key is one whose
    // cached value is still there afterwards.
    const survives = (key: readonly unknown[]) => {
      queryClient.setQueryData(key, { seeded: true });
      return () => queryClient.getQueryData(key) !== undefined;
    };

    it("drops guild-scoped data but keeps the cross-guild personal keys", async () => {
      const guildScoped = survives(["/api/v1/g/5/projects/"]);
      const guildList = survives(["/api/v1/guilds/"]);
      const currentUser = survives(["/api/v1/users/me"]);
      const version = survives(["/api/v1/version"]);
      // The recents bar spans every community, so a switch must not blank it.
      const recents = survives(["/api/v1/recents/"]);

      await resetGuildScopedQueries();

      expect(guildScoped()).toBe(false);
      expect(guildList()).toBe(true);
      expect(currentUser()).toBe(true);
      expect(version()).toBe(true);
      expect(recents()).toBe(true);
    });
  });
});

/**
 * Read state and ballots are written into the cache rather than refetched:
 * invalidating for either would refetch the board mid-scroll, moving rows
 * under the cursor and — with the unread filter on — deleting the one being
 * read. That only works if the patch reaches every shape a post is cached in,
 * and the board is the one that is easy to miss: it scrolls rather than pages,
 * so its cache is an infinite query's `{ pages: [...] }` and not a single page
 * of items.
 */
describe("patchCachedPost", () => {
  beforeEach(() => {
    queryClient.clear();
    setInvalidationGuild(null);
  });

  afterEach(() => {
    queryClient.clear();
    setInvalidationGuild(null);
  });

  const markRead = (post: Record<string, unknown>) => ({ ...post, is_read: true });

  it("patches a post inside an infinite feed's pages", () => {
    const key = ["/api/v1/g/5/posts/", { initiative_id: 1 }];
    queryClient.setQueryData(key, {
      pageParams: [1, 2],
      pages: [
        { items: [{ id: 1, is_read: false }], page: 1 },
        { items: [{ id: 2, is_read: false }], page: 2 },
      ],
    });

    patchCachedPost(2, markRead);

    const data = queryClient.getQueryData(key) as {
      pages: { items: { id: number; is_read: boolean }[] }[];
    };
    expect(data.pages[1].items[0].is_read).toBe(true);
    expect(data.pages[0].items[0].is_read).toBe(false);
  });

  it("leaves untouched pages identical, so their cards do not re-render", () => {
    const key = ["/api/v1/g/5/posts/"];
    const untouched = { items: [{ id: 1, is_read: false }], page: 1 };
    queryClient.setQueryData(key, {
      pageParams: [1, 2],
      pages: [untouched, { items: [{ id: 2, is_read: false }], page: 2 }],
    });

    patchCachedPost(2, markRead);

    const data = queryClient.getQueryData(key) as { pages: unknown[] };
    expect(data.pages[0]).toBe(untouched);
  });

  it("still patches a single page of items and a single post", () => {
    const listKey = ["/api/v1/g/5/posts/"];
    const postKey = ["/api/v1/g/5/posts/7"];
    queryClient.setQueryData(listKey, { items: [{ id: 7, is_read: false }] });
    queryClient.setQueryData(postKey, { id: 7, is_read: false });

    patchCachedPost(7, markRead);

    expect(
      (queryClient.getQueryData(listKey) as { items: { is_read: boolean }[] }).items[0].is_read
    ).toBe(true);
    expect((queryClient.getQueryData(postKey) as { is_read: boolean }).is_read).toBe(true);
  });
});
