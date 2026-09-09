/**
 * Letting go of a community the user no longer belongs to.
 *
 * Deleting the shard is only half of it: the departed community's queries are
 * still sitting in the query client, and a save landing afterwards would write
 * the shard straight back from memory. These pin the order that makes the prune
 * stick, and the grant case that must survive it.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

// The offline cache is native-only, so this file asks for a native platform
// rather than the suite-wide web default.
vi.mock("@capacitor/core", () => ({
  Capacitor: {
    isNativePlatform: () => true,
    getPlatform: () => "android",
    convertFileSrc: (url: string) => url,
  },
  registerPlugin: () => ({}),
}));

import { queryClient } from "@/lib/queryClient";

import { retainOnlyGuilds, setGrantOnlyGuildIds, shouldPersistQuery } from "./offlineCache";

const seed = (key: string) => {
  queryClient.setQueryData([key], { seeded: true });
};

const held = (key: string) => queryClient.getQueryData([key]) !== undefined;

beforeEach(() => {
  queryClient.clear();
  setGrantOnlyGuildIds([]);
});

describe("retainOnlyGuilds", () => {
  it("drops a departed community's queries out of the client", async () => {
    seed("/api/v1/g/3/tasks");
    seed("/api/v1/g/5/tasks");

    await retainOnlyGuilds([3], [3]);

    expect(held("/api/v1/g/3/tasks")).toBe(true);
    expect(held("/api/v1/g/5/tasks")).toBe(false);
  });

  it("leaves the departed community with nothing a later save could write back", async () => {
    seed("/api/v1/g/5/tasks");
    await retainOnlyGuilds([3], [3]);

    // Whatever the persister is asked to write next, the queries that would
    // have recreated the shard are no longer there to be dehydrated.
    const remaining = queryClient
      .getQueryCache()
      .getAll()
      .filter((query) => shouldPersistQuery(query));
    expect(remaining.map((query) => query.queryKey[0])).not.toContain("/api/v1/g/5/tasks");
  });

  it("keeps a community reached by a live grant usable, while refusing it disk", async () => {
    seed("/api/v1/g/9/tasks");
    setGrantOnlyGuildIds([9]);

    // Reachable (the grant is live) but not cacheable (it can end while away).
    await retainOnlyGuilds([3, 9], [3]);

    expect(held("/api/v1/g/9/tasks")).toBe(true);
    // Still barred from disk by the grant exclusion, which the prune leaves be.
    const query = queryClient.getQueryCache().find({ queryKey: ["/api/v1/g/9/tasks"] });
    expect(query && shouldPersistQuery(query)).toBe(false);
  });

  it("leaves platform-level queries alone", async () => {
    seed("/api/v1/users/me");
    seed("/api/v1/me/tasks");

    await retainOnlyGuilds([3], [3]);

    expect(held("/api/v1/users/me")).toBe(true);
    expect(held("/api/v1/me/tasks")).toBe(true);
  });

  it("leaves hand-written keys alone — they name no community", async () => {
    queryClient.setQueryData(["dm", "unread"], { seeded: true });

    await retainOnlyGuilds([3], [3]);

    expect(queryClient.getQueryData(["dm", "unread"])).toBeDefined();
  });
});
