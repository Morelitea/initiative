/**
 * Per-community storage buys a cheaper launch and the ability to forget one
 * community, and takes on one obligation in exchange: a blob nothing rewrites
 * is a blob nothing removes. These pin both halves — what survives, and what is
 * cleaned up — because getting the second wrong leaves content on a device
 * after it should be gone.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

import { createShardedPersister, type PersistedClientLike } from "./offlineShards";

const MAX_AGE = 24 * 60 * 60 * 1000;

/** An in-memory ShardStore, so the tests read what was actually written. */
const makeStore = () => {
  const data = new Map<string, string>();
  return {
    data,
    getItem: async (key: string) => data.get(key) ?? null,
    setItem: async (key: string, value: string) => {
      data.set(key, value);
    },
    removeItem: async (key: string) => {
      data.delete(key);
    },
  };
};

const query = (key: string) => ({ queryKey: [key], queryHash: key, state: { data: 1 } });

const client = (keys: string[], buster = "v1"): PersistedClientLike =>
  ({
    timestamp: Date.now(),
    buster,
    clientState: { mutations: [], queries: keys.map(query) },
  }) as unknown as PersistedClientLike;

/** Shard = the guild in the path, else the platform shard. */
const shardOf = (queryKey: readonly unknown[]) => {
  const first = queryKey[0];
  if (typeof first !== "string") return "platform";
  const match = first.match(/^\/api\/v1\/g\/(\d+)/);
  return match ? `g${match[1]}` : "platform";
};

const build = (store: ReturnType<typeof makeStore>, bootShards: () => string[]) =>
  createShardedPersister({ store, maxAgeMs: MAX_AGE, shardOf, bootShards });

let store: ReturnType<typeof makeStore>;

beforeEach(() => {
  vi.useRealTimers();
  store = makeStore();
});

describe("splitting the cache by community", () => {
  it("writes one blob per community plus one for everything else", async () => {
    const p = build(store, () => ["platform"]);
    await p.persistClient(client(["/api/v1/g/3/tasks", "/api/v1/g/5/tasks", "/api/v1/users/me"]));

    expect([...store.data.keys()].sort()).toEqual([
      "react-query:g3",
      "react-query:g5",
      "react-query:index",
      "react-query:platform",
    ]);
  });

  it("restores only the shards this launch asked for", async () => {
    const writer = build(store, () => ["platform"]);
    await writer.persistClient(
      client(["/api/v1/g/3/tasks", "/api/v1/g/5/tasks", "/api/v1/users/me"])
    );

    const reader = build(store, () => ["platform", "g3"]);
    const restored = await reader.restoreClient();

    const keys = restored?.clientState.queries.map((q) => q.queryKey[0]).sort();
    expect(keys).toEqual(["/api/v1/g/3/tasks", "/api/v1/users/me"]);
    // g5 is untouched on disk — not wanted is not the same as not kept.
    expect(store.data.has("react-query:g5")).toBe(true);
  });

  it("brings a community in when it is opened later", async () => {
    const writer = build(store, () => ["platform"]);
    await writer.persistClient(client(["/api/v1/g/5/tasks"]));

    const reader = build(store, () => ["platform"]);
    await reader.restoreClient();
    const later = await reader.readShard("g5");

    expect(later?.map((q) => q.queryKey[0])).toEqual(["/api/v1/g/5/tasks"]);
  });

  it("does not rewrite a shard whose content has not changed", async () => {
    const p = build(store, () => ["platform"]);
    await p.persistClient(client(["/api/v1/g/3/tasks"]));
    const first = store.data.get("react-query:g3");

    await p.persistClient(client(["/api/v1/g/3/tasks"]));

    expect(store.data.get("react-query:g3")).toBe(first);
  });
});

describe("cleaning up after itself", () => {
  it("deletes a shard that was restored and is now empty", async () => {
    const writer = build(store, () => ["platform"]);
    await writer.persistClient(client(["/api/v1/g/3/tasks", "/api/v1/users/me"]));

    const p = build(store, () => ["platform", "g3"]);
    await p.restoreClient();
    // The user left g3, so its queries are gone from the client.
    await p.persistClient(client(["/api/v1/users/me"]));

    expect(store.data.has("react-query:g3")).toBe(false);
  });

  it("leaves a shard alone when this session never restored it", async () => {
    const writer = build(store, () => ["platform"]);
    await writer.persistClient(client(["/api/v1/g/3/tasks", "/api/v1/users/me"]));

    // A launch that only wants the platform shard must not read g3's absence
    // from the client as "g3 was emptied".
    const p = build(store, () => ["platform"]);
    await p.restoreClient();
    await p.persistClient(client(["/api/v1/users/me"]));

    expect(store.data.has("react-query:g3")).toBe(true);
  });

  it("sweeps a shard past the window even though nothing opened it", async () => {
    vi.useFakeTimers();
    const writer = build(store, () => ["platform"]);
    await writer.persistClient(client(["/api/v1/g/3/tasks", "/api/v1/users/me"]));

    vi.advanceTimersByTime(MAX_AGE + 1000);

    const p = build(store, () => ["platform"]);
    await p.restoreClient();

    expect(store.data.has("react-query:g3")).toBe(false);
    expect(store.data.has("react-query:platform")).toBe(false);
  });

  it("refuses a shard left behind by a different buster", async () => {
    const writer = build(store, () => ["platform"]);
    await writer.persistClient(client(["/api/v1/g/3/tasks"], "v1"));
    // Simulate a shard written under an older buster than the index.
    store.data.set(
      "react-query:g3",
      JSON.stringify({ timestamp: Date.now(), buster: "stale", clientState: { queries: [] } })
    );

    const p = build(store, () => ["platform", "g3"]);
    const restored = await p.restoreClient();

    expect(restored?.clientState.queries).toEqual([]);
    expect(store.data.has("react-query:g3")).toBe(false);
  });

  it("forgets one community without touching another", async () => {
    const p = build(store, () => ["platform"]);
    await p.persistClient(client(["/api/v1/g/3/tasks", "/api/v1/g/5/tasks"]));

    await p.forgetShard("g3");

    expect(store.data.has("react-query:g3")).toBe(false);
    expect(store.data.has("react-query:g5")).toBe(true);
  });

  it("removes every shard and the index when the cache is purged", async () => {
    const p = build(store, () => ["platform"]);
    await p.persistClient(client(["/api/v1/g/3/tasks", "/api/v1/g/5/tasks", "/api/v1/users/me"]));

    await p.removeClient();

    expect([...store.data.keys()]).toEqual([]);
  });

  it("purges shards it never loaded, reading the index to find them", async () => {
    const writer = build(store, () => ["platform"]);
    await writer.persistClient(client(["/api/v1/g/3/tasks", "/api/v1/g/5/tasks"]));

    // A fresh persister that has restored nothing — startup discarding a cache
    // with no session snapshot beside it.
    const fresh = build(store, () => ["platform"]);
    await fresh.removeClient();

    expect([...store.data.keys()]).toEqual([]);
  });

  it("has nothing to restore before anything was written", async () => {
    const p = build(store, () => ["platform"]);
    expect(await p.restoreClient()).toBeUndefined();
  });
});
