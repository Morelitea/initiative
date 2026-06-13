import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useRef } from "react";
import { useTranslation } from "react-i18next";

import {
  addCounterApiV1GGuildIdCounterGroupsGroupIdCountersPost,
  createCounterGroupApiV1GGuildIdCounterGroupsPost,
  decrementCounterApiV1GGuildIdCounterGroupsGroupIdCountersCounterIdDecrementPost,
  deleteCounterApiV1GGuildIdCounterGroupsGroupIdCountersCounterIdDelete,
  deleteCounterGroupApiV1GGuildIdCounterGroupsGroupIdDelete,
  duplicateCounterGroupApiV1GGuildIdCounterGroupsGroupIdDuplicatePost,
  getListCounterGroupsApiV1GGuildIdCounterGroupsGetQueryKey,
  getReadCounterGroupApiV1GGuildIdCounterGroupsGroupIdGetQueryKey,
  incrementCounterApiV1GGuildIdCounterGroupsGroupIdCountersCounterIdIncrementPost,
  listCounterGroupsApiV1GGuildIdCounterGroupsGet,
  readCounterGroupApiV1GGuildIdCounterGroupsGroupIdGet,
  resetAllCountersApiV1GGuildIdCounterGroupsGroupIdResetAllPost,
  resetCounterApiV1GGuildIdCounterGroupsGroupIdCountersCounterIdResetPost,
  setCounterCountApiV1GGuildIdCounterGroupsGroupIdCountersCounterIdSetPost,
  setCounterGroupPermissionsApiV1GGuildIdCounterGroupsGroupIdPermissionsPut,
  setCounterGroupRolePermissionsApiV1GGuildIdCounterGroupsGroupIdRolePermissionsPut,
  sortCountersApiV1GGuildIdCounterGroupsGroupIdSortPost,
  updateCounterApiV1GGuildIdCounterGroupsGroupIdCountersCounterIdPatch,
  updateCounterGroupApiV1GGuildIdCounterGroupsGroupIdPatch,
} from "@/api/generated/counters/counters";
import type {
  CounterCreate,
  CounterGroupCreate,
  CounterGroupDuplicateRequest,
  CounterGroupListResponse,
  CounterGroupPermissionCreate,
  CounterGroupPermissionRead,
  CounterGroupRead,
  CounterGroupRolePermissionCreate,
  CounterGroupRolePermissionRead,
  CounterGroupUpdate,
  CounterRead,
  CounterSetCountRequest,
  CounterSortRequest,
  CounterUpdate,
  ListCounterGroupsApiV1GGuildIdCounterGroupsGetParams,
} from "@/api/generated/initiativeAPI.schemas";
import { invalidateAllCounterGroups, invalidateCounterGroup } from "@/api/query-keys";
import { useActiveGuildId } from "@/hooks/useActiveGuildId";
import { toast } from "@/lib/chesterToast";
import {
  optimisticDecrement,
  optimisticIncrement,
  optimisticReset,
  optimisticSetCount,
} from "@/lib/counter-math";
import { fireCounterStepFeedback } from "@/lib/counterStepFeedback";
import type { MutationOpts } from "@/types/mutation";
import type { QueryOpts } from "@/types/query";

// ── Optimistic update helpers ───────────────────────────────────────────────

interface OptimisticContext {
  previousGroup: CounterGroupRead | undefined;
}

const patchCounterInCache = (
  queryClient: ReturnType<typeof useQueryClient>,
  guildId: number,
  groupId: number,
  counterId: number,
  patch: Partial<CounterRead> | ((c: CounterRead) => Partial<CounterRead>)
): OptimisticContext => {
  const key = getReadCounterGroupApiV1GGuildIdCounterGroupsGroupIdGetQueryKey(guildId, groupId);
  const previousGroup = queryClient.getQueryData<CounterGroupRead>(key);
  queryClient.setQueryData<CounterGroupRead>(key, (old) => {
    if (!old) return old;
    return {
      ...old,
      counters: old.counters.map((c) => {
        if (c.id !== counterId) return c;
        const next = typeof patch === "function" ? patch(c) : patch;
        return { ...c, ...next };
      }),
    };
  });
  return { previousGroup };
};

const rollbackGroup = (
  queryClient: ReturnType<typeof useQueryClient>,
  guildId: number,
  groupId: number,
  context: OptimisticContext | undefined
) => {
  if (!context?.previousGroup) return;
  const key = getReadCounterGroupApiV1GGuildIdCounterGroupsGroupIdGetQueryKey(guildId, groupId);
  queryClient.setQueryData<CounterGroupRead>(key, context.previousGroup);
};

// ── Queries ─────────────────────────────────────────────────────────────────

export const useCounterGroupsList = (
  params: ListCounterGroupsApiV1GGuildIdCounterGroupsGetParams,
  options?: QueryOpts<CounterGroupListResponse>
) => {
  const guildId = useActiveGuildId();
  return useQuery<CounterGroupListResponse>({
    queryKey: getListCounterGroupsApiV1GGuildIdCounterGroupsGetQueryKey(guildId, params),
    queryFn: () =>
      listCounterGroupsApiV1GGuildIdCounterGroupsGet(
        guildId,
        params
      ) as unknown as Promise<CounterGroupListResponse>,
    placeholderData: keepPreviousData,
    ...options,
  });
};

export const useCounterGroup = (groupId: number | null, options?: QueryOpts<CounterGroupRead>) => {
  const guildId = useActiveGuildId();
  const { enabled: userEnabled = true, ...rest } = options ?? {};
  return useQuery<CounterGroupRead>({
    queryKey: getReadCounterGroupApiV1GGuildIdCounterGroupsGroupIdGetQueryKey(guildId, groupId!),
    queryFn: () =>
      readCounterGroupApiV1GGuildIdCounterGroupsGroupIdGet(
        guildId,
        groupId!
      ) as unknown as Promise<CounterGroupRead>,
    enabled: groupId !== null && Number.isFinite(groupId) && userEnabled,
    ...rest,
  });
};

// ── Group mutations ─────────────────────────────────────────────────────────

export const useCreateCounterGroup = (
  options?: MutationOpts<CounterGroupRead, CounterGroupCreate>
) => {
  const { t } = useTranslation("counters");
  const guildId = useActiveGuildId();
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};
  return useMutation({
    ...rest,
    mutationFn: async (data: CounterGroupCreate) =>
      createCounterGroupApiV1GGuildIdCounterGroupsPost(
        guildId,
        data
      ) as unknown as Promise<CounterGroupRead>,
    onSuccess: (...args) => {
      void invalidateAllCounterGroups();
      onSuccess?.(...args);
    },
    onError: (...args) => {
      toast.error(t("error"));
      onError?.(...args);
    },
    onSettled,
  });
};

export const useUpdateCounterGroup = (
  groupId: number,
  options?: MutationOpts<CounterGroupRead, CounterGroupUpdate>
) => {
  const { t } = useTranslation("counters");
  const guildId = useActiveGuildId();
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};
  return useMutation({
    ...rest,
    mutationFn: async (data: CounterGroupUpdate) =>
      updateCounterGroupApiV1GGuildIdCounterGroupsGroupIdPatch(
        guildId,
        groupId,
        data
      ) as unknown as Promise<CounterGroupRead>,
    onSuccess: (...args) => {
      void invalidateCounterGroup(groupId);
      void invalidateAllCounterGroups();
      onSuccess?.(...args);
    },
    onError: (...args) => {
      toast.error(t("error"));
      onError?.(...args);
    },
    onSettled,
  });
};

export const useDuplicateCounterGroup = (
  groupId: number,
  options?: MutationOpts<CounterGroupRead, CounterGroupDuplicateRequest>
) => {
  const { t } = useTranslation("counters");
  const guildId = useActiveGuildId();
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};
  return useMutation({
    ...rest,
    mutationFn: async (data: CounterGroupDuplicateRequest) =>
      duplicateCounterGroupApiV1GGuildIdCounterGroupsGroupIdDuplicatePost(
        guildId,
        groupId,
        data
      ) as unknown as Promise<CounterGroupRead>,
    onSuccess: (...args) => {
      void invalidateAllCounterGroups();
      onSuccess?.(...args);
    },
    onError: (...args) => {
      toast.error(t("error"));
      onError?.(...args);
    },
    onSettled,
  });
};

export const useDeleteCounterGroup = (options?: MutationOpts<void, number>) => {
  const { t } = useTranslation("counters");
  const guildId = useActiveGuildId();
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};
  return useMutation({
    ...rest,
    mutationFn: async (groupId: number) =>
      deleteCounterGroupApiV1GGuildIdCounterGroupsGroupIdDelete(
        guildId,
        groupId
      ) as unknown as Promise<void>,
    onSuccess: (...args) => {
      void invalidateAllCounterGroups();
      onSuccess?.(...args);
    },
    onError: (...args) => {
      toast.error(t("error"));
      onError?.(...args);
    },
    onSettled,
  });
};

// ── Counter mutations ───────────────────────────────────────────────────────

export const useAddCounter = (
  groupId: number,
  options?: MutationOpts<CounterRead, CounterCreate>
) => {
  const { t } = useTranslation("counters");
  const guildId = useActiveGuildId();
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};
  return useMutation({
    ...rest,
    mutationFn: async (data: CounterCreate) =>
      addCounterApiV1GGuildIdCounterGroupsGroupIdCountersPost(
        guildId,
        groupId,
        data
      ) as unknown as Promise<CounterRead>,
    onSuccess: (...args) => {
      void invalidateCounterGroup(groupId);
      void invalidateAllCounterGroups();
      onSuccess?.(...args);
    },
    onError: (...args) => {
      toast.error(t("error"));
      onError?.(...args);
    },
    onSettled,
  });
};

export interface UpdateCounterInput {
  counterId: number;
  data: CounterUpdate;
}

/** Generic PATCH on a counter. Optimistically applies the patch (which may
 * include `position` from a drag-drop) so the cached order updates immediately;
 * server response on settled corrects any drift. */
export const useUpdateCounter = (
  groupId: number,
  options?: MutationOpts<CounterRead, UpdateCounterInput>
) => {
  const { t } = useTranslation("counters");
  const guildId = useActiveGuildId();
  const queryClient = useQueryClient();
  const { onSuccess, onError, onSettled, onMutate, ...rest } = options ?? {};
  return useMutation<CounterRead, Error, UpdateCounterInput, OptimisticContext>({
    ...rest,
    mutationFn: async ({ counterId, data }) =>
      updateCounterApiV1GGuildIdCounterGroupsGroupIdCountersCounterIdPatch(
        guildId,
        groupId,
        counterId,
        data
      ) as unknown as Promise<CounterRead>,
    onMutate: async (...args) => {
      const [vars] = args;
      const key = getReadCounterGroupApiV1GGuildIdCounterGroupsGroupIdGetQueryKey(guildId, groupId);
      await queryClient.cancelQueries({ queryKey: key });
      const ctx = patchCounterInCache(
        queryClient,
        guildId,
        groupId,
        vars.counterId,
        vars.data as Partial<CounterRead>
      );
      await (onMutate as any)?.(...args);
      return ctx;
    },
    onError: (...args) => {
      const ctx = args[2] as OptimisticContext | undefined;
      rollbackGroup(queryClient, guildId, groupId, ctx);
      toast.error(t("error"));
      (onError as any)?.(...args);
    },
    onSuccess: (...args) => {
      (onSuccess as any)?.(...args);
    },
    onSettled: (...args) => {
      void invalidateCounterGroup(groupId);
      (onSettled as any)?.(...args);
    },
  });
};

export const useDeleteCounter = (groupId: number, options?: MutationOpts<void, number>) => {
  const { t } = useTranslation("counters");
  const guildId = useActiveGuildId();
  const queryClient = useQueryClient();
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};
  return useMutation<void, Error, number, OptimisticContext>({
    ...rest,
    mutationFn: async (counterId: number) =>
      deleteCounterApiV1GGuildIdCounterGroupsGroupIdCountersCounterIdDelete(
        guildId,
        groupId,
        counterId
      ) as unknown as Promise<void>,
    onMutate: async (counterId) => {
      const key = getReadCounterGroupApiV1GGuildIdCounterGroupsGroupIdGetQueryKey(guildId, groupId);
      await queryClient.cancelQueries({ queryKey: key });
      const previousGroup = queryClient.getQueryData<CounterGroupRead>(key);
      queryClient.setQueryData<CounterGroupRead>(key, (old) => {
        if (!old) return old;
        return { ...old, counters: old.counters.filter((c) => c.id !== counterId) };
      });
      return { previousGroup };
    },
    onError: (...args) => {
      const ctx = args[2] as OptimisticContext | undefined;
      rollbackGroup(queryClient, guildId, groupId, ctx);
      toast.error(t("error"));
      (onError as any)?.(...args);
    },
    onSuccess: (...args) => {
      (onSuccess as any)?.(...args);
    },
    onSettled: (...args) => {
      void invalidateCounterGroup(groupId);
      void invalidateAllCounterGroups();
      (onSettled as any)?.(...args);
    },
  });
};

// ── Value operations (all optimistic) ───────────────────────────────────────

export interface SetCountInput {
  counterId: number;
  data: CounterSetCountRequest;
}

export const useSetCount = (
  groupId: number,
  options?: MutationOpts<CounterRead, SetCountInput>
) => {
  const { t } = useTranslation("counters");
  const guildId = useActiveGuildId();
  const queryClient = useQueryClient();
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};
  return useMutation<CounterRead, Error, SetCountInput, OptimisticContext>({
    ...rest,
    mutationFn: async ({ counterId, data }) =>
      setCounterCountApiV1GGuildIdCounterGroupsGroupIdCountersCounterIdSetPost(
        guildId,
        groupId,
        counterId,
        data
      ) as unknown as Promise<CounterRead>,
    onMutate: async ({ counterId, data }) => {
      const key = getReadCounterGroupApiV1GGuildIdCounterGroupsGroupIdGetQueryKey(guildId, groupId);
      await queryClient.cancelQueries({ queryKey: key });
      return patchCounterInCache(queryClient, guildId, groupId, counterId, (c) => ({
        count: optimisticSetCount(c, String(data.count)),
      }));
    },
    onError: (...args) => {
      const ctx = args[2] as OptimisticContext | undefined;
      rollbackGroup(queryClient, guildId, groupId, ctx);
      toast.error(t("error"));
      (onError as any)?.(...args);
    },
    onSuccess: (...args) => {
      (onSuccess as any)?.(...args);
    },
    onSettled: (...args) => {
      void invalidateCounterGroup(groupId);
      (onSettled as any)?.(...args);
    },
  });
};

const makeValueOpHook = (
  endpoint: typeof incrementCounterApiV1GGuildIdCounterGroupsGroupIdCountersCounterIdIncrementPost,
  computeOptimistic: (counter: CounterRead) => string
) => {
  return (groupId: number, options?: MutationOpts<CounterRead, number>) => {
    // eslint-disable-next-line react-hooks/rules-of-hooks
    const { t } = useTranslation("counters");
    // eslint-disable-next-line react-hooks/rules-of-hooks
    const guildId = useActiveGuildId();
    // eslint-disable-next-line react-hooks/rules-of-hooks
    const queryClient = useQueryClient();
    const { onSuccess, onError, onSettled, ...rest } = options ?? {};
    // eslint-disable-next-line react-hooks/rules-of-hooks
    return useMutation<CounterRead, Error, number, OptimisticContext>({
      ...rest,
      mutationFn: async (counterId: number) =>
        endpoint(guildId, groupId, counterId) as unknown as Promise<CounterRead>,
      onMutate: async (counterId) => {
        const key = getReadCounterGroupApiV1GGuildIdCounterGroupsGroupIdGetQueryKey(
          guildId,
          groupId
        );
        await queryClient.cancelQueries({ queryKey: key });
        return patchCounterInCache(queryClient, guildId, groupId, counterId, (c) => ({
          count: computeOptimistic(c),
        }));
      },
      onError: (...args) => {
        const ctx = args[2] as OptimisticContext | undefined;
        rollbackGroup(queryClient, guildId, groupId, ctx);
        toast.error(t("error"));
        (onError as any)?.(...args);
      },
      onSuccess: (...args) => {
        (onSuccess as any)?.(...args);
      },
      onSettled: (...args) => {
        void invalidateCounterGroup(groupId);
        (onSettled as any)?.(...args);
      },
    });
  };
};

export const useIncrementCounter = makeValueOpHook(
  incrementCounterApiV1GGuildIdCounterGroupsGroupIdCountersCounterIdIncrementPost,
  optimisticIncrement
);

export const useDecrementCounter = makeValueOpHook(
  decrementCounterApiV1GGuildIdCounterGroupsGroupIdCountersCounterIdDecrementPost,
  optimisticDecrement
);

export const useResetCounter = makeValueOpHook(
  resetCounterApiV1GGuildIdCounterGroupsGroupIdCountersCounterIdResetPost,
  optimisticReset
);

export const useResetAllCounters = (
  groupId: number,
  options?: MutationOpts<CounterGroupRead, void>
) => {
  const { t } = useTranslation("counters");
  const guildId = useActiveGuildId();
  const queryClient = useQueryClient();
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};
  return useMutation<CounterGroupRead, Error, void, OptimisticContext>({
    ...rest,
    mutationFn: async () =>
      resetAllCountersApiV1GGuildIdCounterGroupsGroupIdResetAllPost(
        guildId,
        groupId
      ) as unknown as Promise<CounterGroupRead>,
    onMutate: async () => {
      const key = getReadCounterGroupApiV1GGuildIdCounterGroupsGroupIdGetQueryKey(guildId, groupId);
      await queryClient.cancelQueries({ queryKey: key });
      const previousGroup = queryClient.getQueryData<CounterGroupRead>(key);
      queryClient.setQueryData<CounterGroupRead>(key, (old) => {
        if (!old) return old;
        return {
          ...old,
          counters: old.counters.map((c) => ({ ...c, count: optimisticReset(c) })),
        };
      });
      return { previousGroup };
    },
    onError: (...args) => {
      const ctx = args[2] as OptimisticContext | undefined;
      rollbackGroup(queryClient, guildId, groupId, ctx);
      toast.error(t("error"));
      (onError as any)?.(...args);
    },
    onSuccess: (...args) => {
      (onSuccess as any)?.(...args);
    },
    onSettled: (...args) => {
      void invalidateCounterGroup(groupId);
      (onSettled as any)?.(...args);
    },
  });
};

/** Comparator mirroring the backend `sort_counters` service: case-insensitive
 * name (or numeric count) with `id` as a deterministic final tie-break, so the
 * optimistic order matches what the server will persist. */
const compareCounters =
  (field: CounterSortRequest["field"], direction: CounterSortRequest["direction"]) =>
  (a: CounterRead, b: CounterRead): number => {
    let cmp: number;
    if (field === "count") {
      cmp = Number(a.count) - Number(b.count);
      if (cmp === 0) cmp = a.name.localeCompare(b.name, undefined, { sensitivity: "base" });
    } else {
      cmp = a.name.localeCompare(b.name, undefined, { sensitivity: "base" });
    }
    if (cmp === 0) cmp = a.id - b.id;
    return direction === "desc" ? -cmp : cmp;
  };

export const useSortCounters = (
  groupId: number,
  options?: MutationOpts<CounterGroupRead, CounterSortRequest>
) => {
  const { t } = useTranslation("counters");
  const guildId = useActiveGuildId();
  const queryClient = useQueryClient();
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};
  return useMutation<CounterGroupRead, Error, CounterSortRequest, OptimisticContext>({
    ...rest,
    mutationFn: async (data: CounterSortRequest) =>
      sortCountersApiV1GGuildIdCounterGroupsGroupIdSortPost(
        guildId,
        groupId,
        data
      ) as unknown as Promise<CounterGroupRead>,
    onMutate: async ({ field, direction }) => {
      const key = getReadCounterGroupApiV1GGuildIdCounterGroupsGroupIdGetQueryKey(guildId, groupId);
      await queryClient.cancelQueries({ queryKey: key });
      const previousGroup = queryClient.getQueryData<CounterGroupRead>(key);
      queryClient.setQueryData<CounterGroupRead>(key, (old) => {
        if (!old) return old;
        const sorted = [...old.counters].sort(compareCounters(field, direction));
        return {
          ...old,
          counters: sorted.map((c, index) => ({ ...c, position: String(index + 1) })),
        };
      });
      return { previousGroup };
    },
    onError: (...args) => {
      const ctx = args[2] as OptimisticContext | undefined;
      rollbackGroup(queryClient, guildId, groupId, ctx);
      toast.error(t("error"));
      (onError as any)?.(...args);
    },
    onSuccess: (...args) => {
      (onSuccess as any)?.(...args);
    },
    onSettled: (...args) => {
      void invalidateCounterGroup(groupId);
      (onSettled as any)?.(...args);
    },
  });
};

// ── Debounced stepper (button-mash coalescing) ──────────────────────────────

const STEP_DEBOUNCE_MS = 300;

/**
 * Coalesces rapid +/- clicks into a single `set` call per counter.
 *
 * Every click updates the React Query cache optimistically (so the UI is
 * instant), but the network call is debounced ~300ms behind the last click
 * and sends ONE `set` with the final value. Mashing "+" ten times yields one
 * request — `set(base + 10*step)` — instead of ten `increment` round-trips,
 * which also collapses the WebSocket broadcast storm to a single event.
 *
 * Correctness under concurrent refetches: the user's intended value is held
 * in a `pending` ref (NOT just the cache). A query-cache subscription
 * re-asserts that target over any external write — e.g. the WebSocket echo of
 * our own `set`, or a background refetch — so clicks that land *while a `set`
 * is in flight* are never clobbered by a now-stale server value. The pending
 * entry clears only once the server has confirmed the latest target.
 *
 * This is a be-polite-to-the-server optimization for well-behaved clients; it
 * is NOT an abuse defense (a hostile client can hit the endpoint directly).
 * Server-side rate limiting is the control for that.
 */
export const useSteppedCount = (groupId: number) => {
  const { t } = useTranslation("counters");
  const guildId = useActiveGuildId();
  const queryClient = useQueryClient();
  const timers = useRef<Map<number, ReturnType<typeof setTimeout>>>(new Map());
  // counterId -> value the user is steering toward. Survives refetches until
  // the server confirms it, so in-flight clicks are never lost.
  const pending = useRef<Map<number, string>>(new Map());

  const groupKey = useMemo(
    () => getReadCounterGroupApiV1GGuildIdCounterGroupsGroupIdGetQueryKey(guildId, groupId),
    [guildId, groupId]
  );

  const applyToCache = useCallback(
    (counterId: number, value: string) => {
      queryClient.setQueryData<CounterGroupRead>(groupKey, (old) => {
        if (!old) return old;
        return {
          ...old,
          counters: old.counters.map((c) => (c.id === counterId ? { ...c, count: value } : c)),
        };
      });
    },
    [queryClient, groupKey]
  );

  const sendSet = useCallback(
    async (counterId: number) => {
      const target = pending.current.get(counterId);
      if (target === undefined) return;
      try {
        await setCounterCountApiV1GGuildIdCounterGroupsGroupIdCountersCounterIdSetPost(
          guildId,
          groupId,
          counterId,
          {
            count: target,
          }
        );
        // Stop tracking only if no newer clicks landed mid-flight and nothing
        // is scheduled — otherwise the next flush owns the (newer) target.
        if (pending.current.get(counterId) === target && !timers.current.has(counterId)) {
          pending.current.delete(counterId);
        }
      } catch {
        toast.error(t("error"));
        pending.current.delete(counterId);
        void invalidateCounterGroup(groupId);
      }
    },
    [guildId, groupId, t]
  );

  const flush = useCallback(
    (counterId: number) => {
      timers.current.delete(counterId);
      void sendSet(counterId);
    },
    [sendSet]
  );

  const step = useCallback(
    (counter: CounterRead, direction: 1 | -1) => {
      // Fire audio + haptic per click, before any cache/network work, so
      // rapid presses feel responsive even if the debounced PUT lags.
      fireCounterStepFeedback(direction === 1 ? "up" : "down");

      // Base the next target on the in-memory intent when mid-burst (so a
      // refetch that reset the cache between presses can't lose clicks),
      // otherwise on the freshest cache value.
      const cacheGroup = queryClient.getQueryData<CounterGroupRead>(groupKey);
      const cacheCounter = cacheGroup?.counters.find((c) => c.id === counter.id) ?? counter;
      const basis: CounterRead = {
        ...cacheCounter,
        count: pending.current.get(counter.id) ?? cacheCounter.count,
      };
      const target = direction === 1 ? optimisticIncrement(basis) : optimisticDecrement(basis);

      pending.current.set(counter.id, target);
      applyToCache(counter.id, target);

      const existing = timers.current.get(counter.id);
      if (existing) clearTimeout(existing);
      timers.current.set(
        counter.id,
        setTimeout(() => flush(counter.id), STEP_DEBOUNCE_MS)
      );
    },
    [queryClient, groupKey, applyToCache, flush]
  );

  /** Drop any pending stepped flush for a counter (call before a direct set/reset). */
  const cancel = useCallback((counterId: number) => {
    const timer = timers.current.get(counterId);
    if (timer) clearTimeout(timer);
    timers.current.delete(counterId);
    pending.current.delete(counterId);
  }, []);

  const cancelAll = useCallback(() => {
    for (const timer of timers.current.values()) clearTimeout(timer);
    timers.current.clear();
    pending.current.clear();
  }, []);

  // Re-assert pending targets over any external cache write (WebSocket echo,
  // background refetch) so in-flight clicks survive until the server confirms
  // the latest value. Guard with size === 0 so the common idle case is cheap,
  // and ignore cache events for any query other than this group's so unrelated
  // app-wide mutations during a click burst don't trigger the comparison loop.
  useEffect(() => {
    const cache = queryClient.getQueryCache();
    const groupKeyHash = JSON.stringify(groupKey);
    const unsubscribe = cache.subscribe((event) => {
      if (pending.current.size === 0) return;
      if (JSON.stringify(event.query.queryKey) !== groupKeyHash) return;
      const data = queryClient.getQueryData<CounterGroupRead>(groupKey);
      if (!data) return;
      let changed = false;
      const counters = data.counters.map((c) => {
        const target = pending.current.get(c.id);
        if (target !== undefined && c.count !== target) {
          changed = true;
          return { ...c, count: target };
        }
        return c;
      });
      if (changed) {
        queryClient.setQueryData<CounterGroupRead>(groupKey, { ...data, counters });
      }
    });
    return unsubscribe;
  }, [queryClient, groupKey]);

  // Flush trailing edits on unmount so navigating away doesn't drop them.
  useEffect(() => {
    const timerMap = timers.current;
    const pendingMap = pending.current;
    return () => {
      for (const [counterId, timer] of timerMap) {
        clearTimeout(timer);
        const target = pendingMap.get(counterId);
        if (target !== undefined) {
          void setCounterCountApiV1GGuildIdCounterGroupsGroupIdCountersCounterIdSetPost(
            guildId,
            groupId,
            counterId,
            { count: target }
          );
        }
      }
      timerMap.clear();
      pendingMap.clear();
    };
  }, [guildId, groupId]);

  return {
    increment: (counter: CounterRead) => step(counter, 1),
    decrement: (counter: CounterRead) => step(counter, -1),
    cancel,
    cancelAll,
  };
};

// ── Permission mutations ────────────────────────────────────────────────────

export const useSetCounterGroupPermissions = (
  groupId: number,
  options?: MutationOpts<CounterGroupPermissionRead[], CounterGroupPermissionCreate[]>
) => {
  const { t } = useTranslation("counters");
  const guildId = useActiveGuildId();
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};
  return useMutation({
    ...rest,
    mutationFn: async (data: CounterGroupPermissionCreate[]) =>
      setCounterGroupPermissionsApiV1GGuildIdCounterGroupsGroupIdPermissionsPut(
        guildId,
        groupId,
        data
      ) as unknown as Promise<CounterGroupPermissionRead[]>,
    onSuccess: (...args) => {
      void invalidateCounterGroup(groupId);
      onSuccess?.(...args);
    },
    onError: (...args) => {
      toast.error(t("error"));
      onError?.(...args);
    },
    onSettled,
  });
};

export const useSetCounterGroupRolePermissions = (
  groupId: number,
  options?: MutationOpts<CounterGroupRolePermissionRead[], CounterGroupRolePermissionCreate[]>
) => {
  const { t } = useTranslation("counters");
  const guildId = useActiveGuildId();
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};
  return useMutation({
    ...rest,
    mutationFn: async (data: CounterGroupRolePermissionCreate[]) =>
      setCounterGroupRolePermissionsApiV1GGuildIdCounterGroupsGroupIdRolePermissionsPut(
        guildId,
        groupId,
        data
      ) as unknown as Promise<CounterGroupRolePermissionRead[]>,
    onSuccess: (...args) => {
      void invalidateCounterGroup(groupId);
      onSuccess?.(...args);
    },
    onError: (...args) => {
      toast.error(t("error"));
      onError?.(...args);
    },
    onSettled,
  });
};
