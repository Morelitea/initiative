/**
 * Per-user view preferences hook.
 *
 * Drop-in shape for the old `useState` + `getItem`/`setItem` pattern:
 *
 * ```tsx
 * const [filters, setFilters] = useViewPreference<StoredFilters>(
 *   `project:${projectId}:view-filters`,
 *   DEFAULT_FILTERS,
 * );
 * ```
 *
 * Backed by a single `["user-view-preferences"]` React Query that fetches
 * the entire map once per session. Writes optimistically update the
 * cache and debounce a PUT to the server so rapid filter edits coalesce
 * into one network request. Pending writes are flushed on unmount.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect } from "react";

import type { UserViewPreferencesMap } from "@/api/generated/initiativeAPI.schemas";
import {
  getListViewPreferencesApiV1UserViewPreferencesGetQueryKey,
  listViewPreferencesApiV1UserViewPreferencesGet,
  putViewPreferenceApiV1UserViewPreferencesScopeKeyPut,
} from "@/api/generated/user-view-preferences/user-view-preferences";
import { useAuth } from "@/hooks/useAuth";

/** Coalesce rapid edits into one PUT after the user pauses for this long. */
const WRITE_DEBOUNCE_MS = 400;

/**
 * The cache key for the full preferences map. Exported so the one-shot
 * localStorage migration can prime the cache before the query runs.
 */
export const VIEW_PREFERENCES_QUERY_KEY =
  getListViewPreferencesApiV1UserViewPreferencesGetQueryKey();

/**
 * Module-level debounce map keyed by `scope_key`. Lifting this out of
 * the hook means two consumers of the same scope (rare, but possible)
 * still share one outgoing write window — the most recent target value
 * wins. Survives hot-reload via the eager initialization.
 */
const pendingWrites = new Map<string, { timer: ReturnType<typeof setTimeout>; value: unknown }>();

const flushWrite = async (scopeKey: string): Promise<void> => {
  const pending = pendingWrites.get(scopeKey);
  if (!pending) return;
  pendingWrites.delete(scopeKey);
  await putViewPreferenceApiV1UserViewPreferencesScopeKeyPut(scopeKey, {
    value: pending.value,
  });
};

/**
 * Returns `[value, setValue, { isLoaded }]`.
 *
 * `isLoaded` is false until the initial server fetch resolves; consumers
 * that gate other queries on the persisted filters being available can
 * use it to avoid a redundant "fetch-with-defaults then re-fetch" pair.
 */
export function useViewPreference<T>(
  scopeKey: string,
  fallback: T
): [T, (next: T | ((prev: T) => T)) => void, { isLoaded: boolean }] {
  const queryClient = useQueryClient();
  const { user } = useAuth();

  // Fetch the entire preference map once per session and dedupe across
  // all consumers. Gated on auth: an anonymous bootstrap page (login,
  // forgot password) should not fire this query.
  const query = useQuery<UserViewPreferencesMap>({
    queryKey: VIEW_PREFERENCES_QUERY_KEY,
    queryFn: ({ signal }) => listViewPreferencesApiV1UserViewPreferencesGet(undefined, signal),
    enabled: user !== null,
    // Filter state changes rarely from the server's perspective; we own
    // the source of truth in this client and write through, so a long
    // stale time is fine. Refetches on focus would clobber an optimistic
    // value if a PUT was still in flight.
    staleTime: 5 * 60 * 1000,
    refetchOnWindowFocus: false,
  });

  const value = (query.data?.items?.[scopeKey] as T | undefined) ?? fallback;

  const mutation = useMutation({
    mutationFn: async (scope: string) => flushWrite(scope),
    onError: (_err, scope) => {
      // Server rejected the write — drop our optimistic state and
      // resync from disk so the UI matches reality.
      pendingWrites.delete(scope);
      void queryClient.invalidateQueries({ queryKey: VIEW_PREFERENCES_QUERY_KEY });
    },
  });

  // TanStack Query stabilises `mutate` independently of the `useMutation`
  // result object, which churns reference on every status transition. Depend
  // on `mutate` only so `setValue` stays referentially stable across PUTs;
  // otherwise every downstream useCallback/useEffect that lists `setValue`
  // re-runs after each write.
  const { mutate } = mutation;
  const setValue = useCallback(
    (next: T | ((prev: T) => T)) => {
      // Compute the resolved next value off the *current* cache, not the
      // captured `value` in this closure — multiple setValue calls in a
      // single render should compose.
      const current =
        (queryClient.getQueryData<UserViewPreferencesMap>(VIEW_PREFERENCES_QUERY_KEY)?.items?.[
          scopeKey
        ] as T | undefined) ?? fallback;
      const resolved = typeof next === "function" ? (next as (prev: T) => T)(current) : next;

      queryClient.setQueryData<UserViewPreferencesMap>(VIEW_PREFERENCES_QUERY_KEY, (old) => ({
        items: { ...(old?.items ?? {}), [scopeKey]: resolved },
      }));

      const existing = pendingWrites.get(scopeKey);
      if (existing) clearTimeout(existing.timer);
      pendingWrites.set(scopeKey, {
        value: resolved,
        timer: setTimeout(() => {
          mutate(scopeKey);
        }, WRITE_DEBOUNCE_MS),
      });
    },
    [queryClient, scopeKey, fallback, mutate]
  );

  // Flush any pending write on unmount so navigating away doesn't drop
  // a still-debouncing edit. Pattern mirrors useSteppedCount.
  useEffect(() => {
    return () => {
      const pending = pendingWrites.get(scopeKey);
      if (!pending) return;
      clearTimeout(pending.timer);
      void flushWrite(scopeKey);
    };
  }, [scopeKey]);

  // For unauthenticated callers (which shouldn't happen inside the
  // authenticated tree, but defensively) treat the fallback as loaded
  // so they don't block forever.
  const isLoaded = user === null || query.isSuccess || query.isError;

  return [value, setValue, { isLoaded }];
}
