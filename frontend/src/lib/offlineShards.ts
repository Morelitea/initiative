/**
 * Storing the persisted cache as one blob per community instead of one blob for
 * everything.
 *
 * TanStack's persister interface is deliberately whole-cache: it hands over a
 * single dehydrated client and takes a single one back. That is easy to reason
 * about — every save replaces everything, so anything dropped from the query
 * client disappears from disk on its own — but it means a launch has to parse
 * and hydrate every community's content before the first frame, and there is no
 * way to forget one community without forgetting all of them.
 *
 * Splitting by community buys both. The cost is that a blob nothing rewrites is
 * a blob nothing removes, so this module owns that obligation explicitly:
 *
 *   * the index records when each shard was last written, and a shard past the
 *     max age is deleted at restore without being read;
 *   * a shard that was loaded this session and is now empty is deleted on the
 *     next save;
 *   * a shard that was *not* loaded this session is left alone — its queries
 *     are absent from the client because they were never restored, not because
 *     they were dropped, and deleting on that basis would erase the very
 *     content this exists to keep.
 */

import type { DehydratedState } from "@tanstack/react-query";

export interface ShardStore {
  getItem: (key: string) => Promise<string | null>;
  setItem: (key: string, value: string) => Promise<void>;
  removeItem: (key: string) => Promise<void>;
}

type DehydratedQuery = DehydratedState["queries"][number];

/** Structurally TanStack's `PersistedClient`, without the transitive import. */
export interface PersistedClientLike {
  timestamp: number;
  buster: string;
  clientState: DehydratedState;
}

export interface ShardedPersister {
  persistClient: (client: PersistedClientLike) => Promise<void>;
  restoreClient: () => Promise<PersistedClientLike | undefined>;
  removeClient: () => Promise<void>;
  /** Read one shard's queries, for hydrating a community opened later. */
  readShard: (shard: string) => Promise<DehydratedQuery[] | null>;
  /** Forget one community's content without touching any other. */
  forgetShard: (shard: string) => Promise<void>;
  /** Drop every shard the predicate rejects. For pruning against a membership
   *  list that has just been read from the server. */
  retainShards: (keep: (shard: string) => boolean) => Promise<void>;
}

const KEY_PREFIX = "react-query";
const INDEX_KEY = `${KEY_PREFIX}:index`;
const shardKey = (shard: string) => `${KEY_PREFIX}:${shard}`;

/** `{ shard: when it was last written }`, so staleness is known without a read. */
interface ShardIndex {
  timestamp: number;
  buster: string;
  shards: Record<string, number>;
}

const parse = <T>(raw: string | null): T | null => {
  if (!raw) return null;
  try {
    return JSON.parse(raw) as T;
  } catch {
    return null;
  }
};

interface ShardedPersisterOptions {
  store: ShardStore;
  maxAgeMs: number;
  /** Which shard a query key belongs to — `platform`, or one per community. */
  shardOf: (queryKey: readonly unknown[]) => string;
  /** Shards to hydrate at startup. Everything else waits until it is opened. */
  bootShards: () => string[];
}

export const createShardedPersister = ({
  store,
  maxAgeMs,
  shardOf,
  bootShards,
}: ShardedPersisterOptions): ShardedPersister => {
  /** Shards read or written this session — the only ones a save may delete. */
  const loaded = new Set<string>();
  /** Every shard believed to be on disk, and when each was written. */
  let known: Record<string, number> = {};
  /** Last serialized body per shard, so an unchanged shard is not rewritten. */
  const lastWritten = new Map<string, string>();

  const writeIndex = async (buster: string): Promise<void> => {
    const index: ShardIndex = { timestamp: Date.now(), buster, shards: known };
    await store.setItem(INDEX_KEY, JSON.stringify(index));
  };

  const dropShard = async (shard: string): Promise<void> => {
    delete known[shard];
    lastWritten.delete(shard);
    loaded.delete(shard);
    await store.removeItem(shardKey(shard));
  };

  return {
    persistClient: async (client) => {
      const byShard = new Map<string, DehydratedQuery[]>();
      for (const query of client.clientState.queries) {
        const shard = shardOf(query.queryKey);
        const bucket = byShard.get(shard);
        if (bucket) bucket.push(query);
        else byShard.set(shard, [query]);
      }

      const now = Date.now();
      for (const [shard, queries] of byShard) {
        // Mutations are never persisted, so every shard carries an empty list.
        const body = JSON.stringify({ mutations: [], queries });
        if (lastWritten.get(shard) === body) {
          // Unchanged since the last save — the write would be a no-op, and on
          // a phone the cheapest write is the one that does not happen.
          continue;
        }
        await store.setItem(
          shardKey(shard),
          JSON.stringify({ timestamp: now, buster: client.buster, clientState: JSON.parse(body) })
        );
        lastWritten.set(shard, body);
        known[shard] = now;
        loaded.add(shard);
      }

      // A shard this session actually restored, now holding nothing, has been
      // emptied rather than merely left alone — so it goes.
      for (const shard of [...loaded]) {
        if (!byShard.has(shard)) {
          await dropShard(shard);
        }
      }

      await writeIndex(client.buster);
    },

    restoreClient: async () => {
      const index = parse<ShardIndex>(await store.getItem(INDEX_KEY));
      if (!index || typeof index.timestamp !== "number" || !index.shards) {
        return undefined;
      }
      known = { ...index.shards };

      // Sweep shards that aged out, whether or not this launch wants them.
      // Without this, a community left unopened would keep its content past the
      // window simply because nothing looked at it.
      const now = Date.now();
      let swept = false;
      for (const [shard, savedAt] of Object.entries(known)) {
        if (typeof savedAt !== "number" || now - savedAt > maxAgeMs) {
          await dropShard(shard);
          swept = true;
        }
      }
      // Deleting expired content is safe whatever the session's state, and an
      // offline launch never saves, so the index is corrected here rather than
      // left to a write that may not come.
      if (swept) await writeIndex(index.buster);

      const wanted = new Set(bootShards().filter((shard) => shard in known));
      const queries: DehydratedQuery[] = [];
      for (const shard of wanted) {
        const body = parse<PersistedClientLike>(await store.getItem(shardKey(shard)));
        if (!body || body.buster !== index.buster) {
          await dropShard(shard);
          continue;
        }
        queries.push(...body.clientState.queries);
        lastWritten.set(
          shard,
          JSON.stringify({ mutations: [], queries: body.clientState.queries })
        );
        loaded.add(shard);
      }

      // The index timestamp and buster are handed back unchanged so the caller
      // keeps deciding expiry and busting for the cache as a whole.
      return {
        timestamp: index.timestamp,
        buster: index.buster,
        clientState: { mutations: [], queries },
      };
    },

    removeClient: async () => {
      // The index, not what this session happens to have loaded, is the list of
      // what is on disk. A purge can run before anything was ever restored —
      // startup discarding a cache with no session beside it — and deleting
      // only the shards already in hand would leave the rest behind.
      const index = parse<ShardIndex>(await store.getItem(INDEX_KEY));
      const everything = new Set([...Object.keys(known), ...Object.keys(index?.shards ?? {})]);
      for (const shard of everything) {
        await store.removeItem(shardKey(shard));
      }
      known = {};
      lastWritten.clear();
      loaded.clear();
      await store.removeItem(INDEX_KEY);
    },

    readShard: async (shard) => {
      const body = parse<PersistedClientLike>(await store.getItem(shardKey(shard)));
      const savedAt = known[shard];
      if (!body || typeof savedAt !== "number" || Date.now() - savedAt > maxAgeMs) {
        if (body) await dropShard(shard);
        return null;
      }
      lastWritten.set(shard, JSON.stringify({ mutations: [], queries: body.clientState.queries }));
      loaded.add(shard);
      return body.clientState.queries;
    },

    forgetShard: dropShard,

    retainShards: async (keep) => {
      // The index is the list of what is on disk, not what this session
      // loaded: a community left behind is precisely one nothing has opened.
      const index = parse<ShardIndex>(await store.getItem(INDEX_KEY));
      if (!index?.shards) return;

      const survivors: Record<string, number> = {};
      let changed = false;
      for (const [shard, savedAt] of Object.entries({ ...index.shards, ...known })) {
        if (keep(shard)) {
          survivors[shard] = savedAt;
          continue;
        }
        await store.removeItem(shardKey(shard));
        lastWritten.delete(shard);
        loaded.delete(shard);
        changed = true;
      }
      if (!changed) return;
      known = survivors;
      await writeIndex(index.buster);
    },
  };
};
