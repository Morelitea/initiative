import {
  keepPreviousData,
  type QueryClient,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { useTranslation } from "react-i18next";

import type {
  ListQueuesApiV1GGuildIdQueuesGetParams,
  QueueCreate,
  QueueItemCreate,
  QueueItemRead,
  QueueItemReorderRequest,
  QueueItemUpdate,
  QueueListResponse,
  QueuePermissionCreate,
  QueuePermissionRead,
  QueueRead,
  QueueRolePermissionCreate,
  QueueRolePermissionRead,
  QueueUpdate,
} from "@/api/generated/initiativeAPI.schemas";
import {
  addQueueItemApiV1GGuildIdQueuesQueueIdItemsPost,
  advanceTurnApiV1GGuildIdQueuesQueueIdNextPost,
  createQueueApiV1GGuildIdQueuesPost,
  deleteQueueApiV1GGuildIdQueuesQueueIdDelete,
  deleteQueueItemApiV1GGuildIdQueuesQueueIdItemsItemIdDelete,
  getListQueuesApiV1GGuildIdQueuesGetQueryKey,
  getReadQueueApiV1GGuildIdQueuesQueueIdGetQueryKey,
  holdCurrentTurnApiV1GGuildIdQueuesQueueIdHoldPost,
  listQueuesApiV1GGuildIdQueuesGet,
  previousTurnApiV1GGuildIdQueuesQueueIdPreviousPost,
  readQueueApiV1GGuildIdQueuesQueueIdGet,
  releaseHeldItemApiV1GGuildIdQueuesQueueIdReleaseItemIdPost,
  reorderQueueItemsApiV1GGuildIdQueuesQueueIdItemsReorderPut,
  resetQueueApiV1GGuildIdQueuesQueueIdResetPost,
  setActiveItemApiV1GGuildIdQueuesQueueIdSetActiveItemIdPost,
  setQueueItemDocumentsApiV1GGuildIdQueuesQueueIdItemsItemIdDocumentsPut,
  setQueueItemTagsApiV1GGuildIdQueuesQueueIdItemsItemIdTagsPut,
  setQueueItemTasksApiV1GGuildIdQueuesQueueIdItemsItemIdTasksPut,
  setQueuePermissionsApiV1GGuildIdQueuesQueueIdPermissionsPut,
  setQueueRolePermissionsApiV1GGuildIdQueuesQueueIdRolePermissionsPut,
  startQueueApiV1GGuildIdQueuesQueueIdStartPost,
  stopQueueApiV1GGuildIdQueuesQueueIdStopPost,
  updateQueueApiV1GGuildIdQueuesQueueIdPatch,
  updateQueueItemApiV1GGuildIdQueuesQueueIdItemsItemIdPatch,
} from "@/api/generated/queues/queues";
import { invalidateAllQueues, invalidateQueue } from "@/api/query-keys";
import { useActiveGuildId } from "@/hooks/useActiveGuildId";
import { toast } from "@/lib/chesterToast";
import type { MutationOpts } from "@/types/mutation";
import type { QueryOpts } from "@/types/query";

// ── Queries ─────────────────────────────────────────────────────────────────

export const useQueuesList = (
  params: ListQueuesApiV1GGuildIdQueuesGetParams,
  options?: QueryOpts<QueueListResponse>
) => {
  const guildId = useActiveGuildId();
  return useQuery<QueueListResponse>({
    queryKey: getListQueuesApiV1GGuildIdQueuesGetQueryKey(guildId, params),
    queryFn: () =>
      listQueuesApiV1GGuildIdQueuesGet(guildId, params) as unknown as Promise<QueueListResponse>,
    placeholderData: keepPreviousData,
    ...options,
  });
};

export const useQueue = (queueId: number | null, options?: QueryOpts<QueueRead>) => {
  const guildId = useActiveGuildId();
  const { enabled: userEnabled = true, ...rest } = options ?? {};
  return useQuery<QueueRead>({
    queryKey: getReadQueueApiV1GGuildIdQueuesQueueIdGetQueryKey(guildId, queueId!),
    queryFn: () =>
      readQueueApiV1GGuildIdQueuesQueueIdGet(guildId, queueId!) as unknown as Promise<QueueRead>,
    enabled: queueId !== null && Number.isFinite(queueId) && userEnabled,
    ...rest,
  });
};

// ── Mutations ───────────────────────────────────────────────────────────────

export const useCreateQueue = (options?: MutationOpts<QueueRead, QueueCreate>) => {
  const { t } = useTranslation("queues");
  const guildId = useActiveGuildId();
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async (data: QueueCreate) => {
      return createQueueApiV1GGuildIdQueuesPost(guildId, data) as unknown as Promise<QueueRead>;
    },
    onSuccess: (...args) => {
      void invalidateAllQueues();
      onSuccess?.(...args);
    },
    onError: (...args) => {
      toast.error(t("error"));
      onError?.(...args);
    },
    onSettled,
  });
};

export const useUpdateQueue = (queueId: number, options?: MutationOpts<QueueRead, QueueUpdate>) => {
  const { t } = useTranslation("queues");
  const guildId = useActiveGuildId();
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async (data: QueueUpdate) => {
      return updateQueueApiV1GGuildIdQueuesQueueIdPatch(
        guildId,
        queueId,
        data
      ) as unknown as Promise<QueueRead>;
    },
    onSuccess: (...args) => {
      void invalidateQueue(queueId);
      void invalidateAllQueues();
      onSuccess?.(...args);
    },
    onError: (...args) => {
      toast.error(t("error"));
      onError?.(...args);
    },
    onSettled,
  });
};

export const useDeleteQueue = (options?: MutationOpts<void, number>) => {
  const { t } = useTranslation("queues");
  const guildId = useActiveGuildId();
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async (queueId: number) => {
      await deleteQueueApiV1GGuildIdQueuesQueueIdDelete(guildId, queueId);
    },
    onSuccess: (...args) => {
      void invalidateAllQueues();
      onSuccess?.(...args);
    },
    onError: (...args) => {
      toast.error(t("error"));
      onError?.(...args);
    },
    onSettled,
  });
};

// ── Item Mutations ──────────────────────────────────────────────────────────

export const useCreateQueueItem = (
  queueId: number,
  options?: MutationOpts<QueueItemRead, QueueItemCreate>
) => {
  const { t } = useTranslation("queues");
  const guildId = useActiveGuildId();
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async (data: QueueItemCreate) => {
      return addQueueItemApiV1GGuildIdQueuesQueueIdItemsPost(
        guildId,
        queueId,
        data
      ) as unknown as Promise<QueueItemRead>;
    },
    onSuccess: (...args) => {
      void invalidateQueue(queueId);
      void invalidateAllQueues();
      onSuccess?.(...args);
    },
    onError: (...args) => {
      toast.error(t("error"));
      onError?.(...args);
    },
    onSettled,
  });
};

export const useUpdateQueueItem = (
  queueId: number,
  options?: MutationOpts<QueueItemRead, { itemId: number; data: QueueItemUpdate }>
) => {
  const { t } = useTranslation("queues");
  const guildId = useActiveGuildId();
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async ({ itemId, data }: { itemId: number; data: QueueItemUpdate }) => {
      return updateQueueItemApiV1GGuildIdQueuesQueueIdItemsItemIdPatch(
        guildId,
        queueId,
        itemId,
        data
      ) as unknown as Promise<QueueItemRead>;
    },
    onSuccess: (...args) => {
      void invalidateQueue(queueId);
      void invalidateAllQueues();
      onSuccess?.(...args);
    },
    onError: (...args) => {
      toast.error(t("error"));
      onError?.(...args);
    },
    onSettled,
  });
};

export const useDeleteQueueItem = (queueId: number, options?: MutationOpts<void, number>) => {
  const { t } = useTranslation("queues");
  const guildId = useActiveGuildId();
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async (itemId: number) => {
      await deleteQueueItemApiV1GGuildIdQueuesQueueIdItemsItemIdDelete(guildId, queueId, itemId);
    },
    onSuccess: (...args) => {
      void invalidateQueue(queueId);
      void invalidateAllQueues();
      onSuccess?.(...args);
    },
    onError: (...args) => {
      toast.error(t("error"));
      onError?.(...args);
    },
    onSettled,
  });
};

export const useReorderQueueItems = (
  queueId: number,
  options?: MutationOpts<QueueRead, QueueItemReorderRequest>
) => {
  const { t } = useTranslation("queues");
  const guildId = useActiveGuildId();
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async (data: QueueItemReorderRequest) => {
      return reorderQueueItemsApiV1GGuildIdQueuesQueueIdItemsReorderPut(
        guildId,
        queueId,
        data
      ) as unknown as Promise<QueueRead>;
    },
    onSuccess: (...args) => {
      void invalidateQueue(queueId);
      void invalidateAllQueues();
      onSuccess?.(...args);
    },
    onError: (...args) => {
      toast.error(t("error"));
      onError?.(...args);
    },
    onSettled,
  });
};

// ── Turn Control Mutations ──────────────────────────────────────────────────
//
// Turn changes are applied optimistically: the displayed current item and round
// update instantly in the cache, then reconcile with the server on settle (and
// via the queue WebSocket). The transition logic below mirrors
// `_visible_items_desc` + advance/previous in `backend/app/services/queues.py`;
// keep the two in sync.

type QueueTurnContext = { previous?: QueueRead };

/**
 * Visible items sorted by position-desc, including held items. Used by the
 * `advanceQueueState` walk so it can land on a held item and auto-release it
 * when its due round arrives.
 */
const visibleItemsDesc = (queue: QueueRead): QueueItemRead[] =>
  queue.items.filter((item) => item.is_visible).sort((a, b) => b.position - a.position);

/**
 * Rotation-eligible items (visible AND not held), position-desc. Used by
 * Previous, Start, Reset — anywhere we want to land on an item that's
 * "currently in the rotation" without triggering auto-release semantics.
 */
const activeRotationDesc = (queue: QueueRead): QueueItemRead[] =>
  visibleItemsDesc(queue).filter((item) => item.held_at_round === null);

/** Replace an item inside `queue.items` with `updater(item)`. */
const replaceItem = (
  queue: QueueRead,
  itemId: number,
  updater: (item: QueueItemRead) => QueueItemRead
): QueueItemRead[] => queue.items.map((item) => (item.id === itemId ? updater(item) : item));

/**
 * Advance to the next rotation slot. Mirrors backend `advance_turn`: walks
 * `visibleItemsDesc` (which includes held items) so a held item whose due
 * round has come up can be auto-released; held items not yet due are
 * skipped. See `backend/app/services/queues.py:advance_turn`.
 */
export const advanceQueueState = (queue: QueueRead): QueueRead => {
  const visible = visibleItemsDesc(queue);
  if (visible.length === 0) return queue;

  const currentId = queue.current_item?.id ?? null;
  const startIdx = currentId == null ? -1 : visible.findIndex((item) => item.id === currentId);

  let idx = startIdx;
  let round = queue.current_round;
  let hadStart = startIdx !== -1;
  for (let step = 0; step <= visible.length * 2; step += 1) {
    const nextIdx = (idx + 1) % visible.length;
    if (nextIdx === 0 && hadStart) round += 1;
    const candidate = visible[nextIdx];
    if (candidate.held_at_round === null) {
      return { ...queue, current_item: candidate, current_round: round };
    }
    if (candidate.held_at_round < round) {
      const released: QueueItemRead = { ...candidate, held_at_round: null };
      return {
        ...queue,
        items: replaceItem(queue, candidate.id, () => released),
        current_item: released,
        current_round: round,
      };
    }
    // Held and not yet due — skip; subsequent wraps from here bump the round.
    idx = nextIdx;
    hadStart = true;
  }
  // Every rotation item is held and not yet due — clear current.
  return { ...queue, current_item: null, current_round: round };
};

/**
 * Step backward through the active rotation. Held items are skipped without
 * auto-release — auto-release is a forward-time effect of advance only.
 */
export const previousQueueState = (queue: QueueRead): QueueRead => {
  const rotation = activeRotationDesc(queue);
  if (rotation.length === 0) return queue;
  const currentId = queue.current_item?.id ?? null;
  const idx = currentId == null ? -1 : rotation.findIndex((item) => item.id === currentId);
  if (idx <= 0) {
    return {
      ...queue,
      current_item: rotation[rotation.length - 1],
      current_round: Math.max(1, queue.current_round - 1),
    };
  }
  return { ...queue, current_item: rotation[idx - 1] };
};

export const startQueueState = (queue: QueueRead): QueueRead => {
  const rotation = activeRotationDesc(queue);
  if (rotation.length === 0) return queue;
  return { ...queue, is_active: true, current_item: rotation[0], current_round: 1 };
};

export const stopQueueState = (queue: QueueRead): QueueRead => ({ ...queue, is_active: false });

export const resetQueueState = (queue: QueueRead): QueueRead => {
  const rotation = activeRotationDesc(queue);
  if (rotation.length === 0) return queue;
  return { ...queue, current_round: 1, current_item: rotation[0] };
};

/**
 * Set the current to a specific item. If the target is currently held, clear
 * `held_at_round` on the same write so the invariant "current ∉ held set"
 * holds (mirrors backend `set_active_item`).
 */
export const setActiveItemState = (queue: QueueRead, itemId: number): QueueRead => {
  const target = queue.items.find((i) => i.id === itemId);
  if (!target) return queue;
  if (target.held_at_round !== null) {
    const cleared: QueueItemRead = { ...target, held_at_round: null };
    return {
      ...queue,
      items: replaceItem(queue, itemId, () => cleared),
      current_item: cleared,
    };
  }
  return { ...queue, current_item: target };
};

/**
 * Hold the current turn: stamp it with `held_at_round = current_round` and
 * advance to the next rotation slot. If holding empties the rotation,
 * `current_item` becomes `null` and `current_round` is unchanged.
 */
export const holdCurrentState = (queue: QueueRead): QueueRead => {
  const currentId = queue.current_item?.id ?? null;
  if (currentId == null) return queue;
  const heldRound = queue.current_round;
  const heldItems = replaceItem(queue, currentId, (item) => ({
    ...item,
    held_at_round: heldRound,
  }));
  // Walk position-desc starting from the held item; find the next rotation
  // slot among the updated items.
  const visible = heldItems
    .filter((item) => item.is_visible)
    .sort((a, b) => b.position - a.position);
  const startIdx = visible.findIndex((item) => item.id === currentId);
  let round = queue.current_round;
  for (let step = 1; step <= visible.length; step += 1) {
    const nextIdx = (startIdx + step) % visible.length;
    if (nextIdx <= startIdx) round = queue.current_round + 1;
    const candidate = visible[nextIdx];
    if (candidate.held_at_round === null) {
      return {
        ...queue,
        items: heldItems,
        current_item: candidate,
        current_round: round,
      };
    }
  }
  // No rotation-eligible item left.
  return { ...queue, items: heldItems, current_item: null };
};

export interface ReleaseHeldOptions {
  /**
   * PF2e Delay semantics: the target acts now (becomes the current turn)
   * and its `position` is rewritten to land just above the previous current
   * item. The new initiative slot persists for the rest of the encounter.
   * Default `false` keeps the original position and the current pointer —
   * the released item re-enters at its natural slot.
   */
  reposition?: boolean;
}

/**
 * Manually release a held item back into the active rotation.
 *
 * Clears `held_at_round` on the target. With `reposition: false` (default),
 * `current_item` is intentionally untouched so releasing doesn't rewind the
 * rotation pointer onto items that already took their turn. With
 * `reposition: true`, the target's `position` is rewritten just above the
 * previous current and the target becomes the new current — mirrors backend
 * `release_held(reposition=True)`.
 */
export const releaseHeldState = (
  queue: QueueRead,
  itemId: number,
  options: ReleaseHeldOptions = {}
): QueueRead => {
  const target = queue.items.find((i) => i.id === itemId);
  if (!target || target.held_at_round === null) return queue;

  let nextPosition = target.position;
  let promoteToCurrent = false;
  const currentId = queue.current_item?.id ?? null;
  if (options.reposition && currentId !== null && currentId !== itemId) {
    const current = queue.items.find((i) => i.id === currentId);
    if (current) {
      // Closest active item strictly above current.
      const above = queue.items
        .filter(
          (i) =>
            i.is_visible &&
            i.held_at_round === null &&
            i.id !== itemId &&
            i.id !== current.id &&
            i.position > current.position
        )
        .sort((a, b) => a.position - b.position)[0];
      nextPosition = above ? (current.position + above.position) / 2 : current.position + 1.0;
      promoteToCurrent = true;
    }
  }

  const released: QueueItemRead = {
    ...target,
    held_at_round: null,
    position: nextPosition,
  };
  return {
    ...queue,
    items: replaceItem(queue, itemId, () => released),
    current_item: promoteToCurrent ? released : queue.current_item,
  };
};

/**
 * Synchronously apply an optimistic turn transition. Returns the pre-mutation
 * snapshot so the caller can roll back on error.
 *
 * `cancelQueries` is fired without awaiting — it sends abort signals
 * synchronously, so a racing refetch (e.g. from the queue WebSocket
 * invalidation) won't clobber the value we're about to write. Any background
 * fetch is reconciled by `onSettled`'s invalidation either way.
 */
const applyOptimisticTurn = (
  guildId: number,
  queryClient: QueryClient,
  queueId: number,
  apply: (queue: QueueRead) => QueueRead
): QueueTurnContext => {
  const key = getReadQueueApiV1GGuildIdQueuesQueueIdGetQueryKey(guildId, queueId);
  void queryClient.cancelQueries({ queryKey: key });
  const previous = queryClient.getQueryData<QueueRead>(key);
  if (previous) {
    queryClient.setQueryData<QueueRead>(key, apply(previous));
  }
  return { previous };
};

/** Restore the pre-mutation queue snapshot after a failed turn change. */
const rollbackOptimisticTurn = (
  guildId: number,
  queryClient: QueryClient,
  queueId: number,
  context: QueueTurnContext | undefined
) => {
  if (context?.previous) {
    queryClient.setQueryData(
      getReadQueueApiV1GGuildIdQueuesQueueIdGetQueryKey(guildId, queueId),
      context.previous
    );
  }
};

export const useAdvanceTurn = (queueId: number, options?: MutationOpts<QueueRead, void>) => {
  const { t } = useTranslation("queues");
  const guildId = useActiveGuildId();
  const queryClient = useQueryClient();
  const { onSuccess, onError, onSettled, onMutate: _ignored, ...rest } = options ?? {};

  return useMutation<QueueRead, Error, void, QueueTurnContext>({
    ...rest,
    mutationFn: async () => {
      return advanceTurnApiV1GGuildIdQueuesQueueIdNextPost(
        guildId,
        queueId
      ) as unknown as Promise<QueueRead>;
    },
    onMutate: () => applyOptimisticTurn(guildId, queryClient, queueId, advanceQueueState),
    onSuccess,
    onError: (err, vars, onMutateResult, context) => {
      rollbackOptimisticTurn(guildId, queryClient, queueId, onMutateResult);
      toast.error(t("error"));
      onError?.(err, vars, onMutateResult, context);
    },
    onSettled: (...args) => {
      void invalidateQueue(queueId);
      void invalidateAllQueues();
      onSettled?.(...args);
    },
  });
};

export const usePreviousTurn = (queueId: number, options?: MutationOpts<QueueRead, void>) => {
  const { t } = useTranslation("queues");
  const guildId = useActiveGuildId();
  const queryClient = useQueryClient();
  const { onSuccess, onError, onSettled, onMutate: _ignored, ...rest } = options ?? {};

  return useMutation<QueueRead, Error, void, QueueTurnContext>({
    ...rest,
    mutationFn: async () => {
      return previousTurnApiV1GGuildIdQueuesQueueIdPreviousPost(
        guildId,
        queueId
      ) as unknown as Promise<QueueRead>;
    },
    onMutate: () => applyOptimisticTurn(guildId, queryClient, queueId, previousQueueState),
    onSuccess,
    onError: (err, vars, onMutateResult, context) => {
      rollbackOptimisticTurn(guildId, queryClient, queueId, onMutateResult);
      toast.error(t("error"));
      onError?.(err, vars, onMutateResult, context);
    },
    onSettled: (...args) => {
      void invalidateQueue(queueId);
      void invalidateAllQueues();
      onSettled?.(...args);
    },
  });
};

export const useStartQueue = (queueId: number, options?: MutationOpts<QueueRead, void>) => {
  const { t } = useTranslation("queues");
  const guildId = useActiveGuildId();
  const queryClient = useQueryClient();
  const { onSuccess, onError, onSettled, onMutate: _ignored, ...rest } = options ?? {};

  return useMutation<QueueRead, Error, void, QueueTurnContext>({
    ...rest,
    mutationFn: async () => {
      return startQueueApiV1GGuildIdQueuesQueueIdStartPost(
        guildId,
        queueId
      ) as unknown as Promise<QueueRead>;
    },
    onMutate: () => applyOptimisticTurn(guildId, queryClient, queueId, startQueueState),
    onSuccess,
    onError: (err, vars, onMutateResult, context) => {
      rollbackOptimisticTurn(guildId, queryClient, queueId, onMutateResult);
      toast.error(t("error"));
      onError?.(err, vars, onMutateResult, context);
    },
    onSettled: (...args) => {
      void invalidateQueue(queueId);
      void invalidateAllQueues();
      onSettled?.(...args);
    },
  });
};

export const useStopQueue = (queueId: number, options?: MutationOpts<QueueRead, void>) => {
  const { t } = useTranslation("queues");
  const guildId = useActiveGuildId();
  const queryClient = useQueryClient();
  const { onSuccess, onError, onSettled, onMutate: _ignored, ...rest } = options ?? {};

  return useMutation<QueueRead, Error, void, QueueTurnContext>({
    ...rest,
    mutationFn: async () => {
      return stopQueueApiV1GGuildIdQueuesQueueIdStopPost(
        guildId,
        queueId
      ) as unknown as Promise<QueueRead>;
    },
    onMutate: () => applyOptimisticTurn(guildId, queryClient, queueId, stopQueueState),
    onSuccess,
    onError: (err, vars, onMutateResult, context) => {
      rollbackOptimisticTurn(guildId, queryClient, queueId, onMutateResult);
      toast.error(t("error"));
      onError?.(err, vars, onMutateResult, context);
    },
    onSettled: (...args) => {
      void invalidateQueue(queueId);
      void invalidateAllQueues();
      onSettled?.(...args);
    },
  });
};

export const useResetQueue = (queueId: number, options?: MutationOpts<QueueRead, void>) => {
  const { t } = useTranslation("queues");
  const guildId = useActiveGuildId();
  const queryClient = useQueryClient();
  const { onSuccess, onError, onSettled, onMutate: _ignored, ...rest } = options ?? {};

  return useMutation<QueueRead, Error, void, QueueTurnContext>({
    ...rest,
    mutationFn: async () => {
      return resetQueueApiV1GGuildIdQueuesQueueIdResetPost(
        guildId,
        queueId
      ) as unknown as Promise<QueueRead>;
    },
    onMutate: () => applyOptimisticTurn(guildId, queryClient, queueId, resetQueueState),
    onSuccess,
    onError: (err, vars, onMutateResult, context) => {
      rollbackOptimisticTurn(guildId, queryClient, queueId, onMutateResult);
      toast.error(t("error"));
      onError?.(err, vars, onMutateResult, context);
    },
    onSettled: (...args) => {
      void invalidateQueue(queueId);
      void invalidateAllQueues();
      onSettled?.(...args);
    },
  });
};

export const useSetActiveItem = (queueId: number, options?: MutationOpts<QueueRead, number>) => {
  const { t } = useTranslation("queues");
  const guildId = useActiveGuildId();
  const queryClient = useQueryClient();
  const { onSuccess, onError, onSettled, onMutate: _ignored, ...rest } = options ?? {};

  return useMutation<QueueRead, Error, number, QueueTurnContext>({
    ...rest,
    mutationFn: async (itemId: number) => {
      return setActiveItemApiV1GGuildIdQueuesQueueIdSetActiveItemIdPost(
        guildId,
        queueId,
        itemId
      ) as unknown as Promise<QueueRead>;
    },
    onMutate: (itemId) =>
      applyOptimisticTurn(guildId, queryClient, queueId, (queue) =>
        setActiveItemState(queue, itemId)
      ),
    onSuccess,
    onError: (err, vars, onMutateResult, context) => {
      rollbackOptimisticTurn(guildId, queryClient, queueId, onMutateResult);
      toast.error(t("error"));
      onError?.(err, vars, onMutateResult, context);
    },
    onSettled: (...args) => {
      void invalidateQueue(queueId);
      void invalidateAllQueues();
      onSettled?.(...args);
    },
  });
};

export const useHoldCurrent = (queueId: number, options?: MutationOpts<QueueRead, void>) => {
  const { t } = useTranslation("queues");
  const guildId = useActiveGuildId();
  const queryClient = useQueryClient();
  const { onSuccess, onError, onSettled, onMutate: _ignored, ...rest } = options ?? {};

  return useMutation<QueueRead, Error, void, QueueTurnContext>({
    ...rest,
    mutationFn: async () => {
      return holdCurrentTurnApiV1GGuildIdQueuesQueueIdHoldPost(
        guildId,
        queueId
      ) as unknown as Promise<QueueRead>;
    },
    onMutate: () => applyOptimisticTurn(guildId, queryClient, queueId, holdCurrentState),
    onSuccess,
    onError: (err, vars, onMutateResult, context) => {
      rollbackOptimisticTurn(guildId, queryClient, queueId, onMutateResult);
      toast.error(t("error"));
      onError?.(err, vars, onMutateResult, context);
    },
    onSettled: (...args) => {
      void invalidateQueue(queueId);
      void invalidateAllQueues();
      onSettled?.(...args);
    },
  });
};

export interface ReleaseHeldVariables {
  itemId: number;
  /** PF2e Delay: reposition the released item just below current. */
  reposition?: boolean;
}

export const useReleaseHeld = (
  queueId: number,
  options?: MutationOpts<QueueRead, ReleaseHeldVariables>
) => {
  const { t } = useTranslation("queues");
  const guildId = useActiveGuildId();
  const queryClient = useQueryClient();
  const { onSuccess, onError, onSettled, onMutate: _ignored, ...rest } = options ?? {};

  return useMutation<QueueRead, Error, ReleaseHeldVariables, QueueTurnContext>({
    ...rest,
    mutationFn: async ({ itemId, reposition }) => {
      return releaseHeldItemApiV1GGuildIdQueuesQueueIdReleaseItemIdPost(guildId, queueId, itemId, {
        reposition: reposition ?? false,
      }) as unknown as Promise<QueueRead>;
    },
    onMutate: ({ itemId, reposition }) =>
      applyOptimisticTurn(guildId, queryClient, queueId, (queue) =>
        releaseHeldState(queue, itemId, { reposition })
      ),
    onSuccess,
    onError: (err, vars, onMutateResult, context) => {
      rollbackOptimisticTurn(guildId, queryClient, queueId, onMutateResult);
      toast.error(t("error"));
      onError?.(err, vars, onMutateResult, context);
    },
    onSettled: (...args) => {
      void invalidateQueue(queueId);
      void invalidateAllQueues();
      onSettled?.(...args);
    },
  });
};

// ── Item Association Mutations ──────────────────────────────────────────────

export const useSetQueueItemTags = (
  queueId: number,
  options?: MutationOpts<QueueItemRead, { itemId: number; tagIds: number[] }>
) => {
  const { t } = useTranslation("queues");
  const guildId = useActiveGuildId();
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async ({ itemId, tagIds }: { itemId: number; tagIds: number[] }) => {
      return setQueueItemTagsApiV1GGuildIdQueuesQueueIdItemsItemIdTagsPut(
        guildId,
        queueId,
        itemId,
        tagIds
      ) as unknown as Promise<QueueItemRead>;
    },
    onSuccess: (...args) => {
      void invalidateQueue(queueId);
      void invalidateAllQueues();
      onSuccess?.(...args);
    },
    onError: (...args) => {
      toast.error(t("error"));
      onError?.(...args);
    },
    onSettled,
  });
};

export const useSetQueueItemDocuments = (
  queueId: number,
  options?: MutationOpts<QueueItemRead, { itemId: number; documentIds: number[] }>
) => {
  const { t } = useTranslation("queues");
  const guildId = useActiveGuildId();
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async ({ itemId, documentIds }: { itemId: number; documentIds: number[] }) => {
      return setQueueItemDocumentsApiV1GGuildIdQueuesQueueIdItemsItemIdDocumentsPut(
        guildId,
        queueId,
        itemId,
        documentIds
      ) as unknown as Promise<QueueItemRead>;
    },
    onSuccess: (...args) => {
      void invalidateQueue(queueId);
      void invalidateAllQueues();
      onSuccess?.(...args);
    },
    onError: (...args) => {
      toast.error(t("error"));
      onError?.(...args);
    },
    onSettled,
  });
};

export const useSetQueueItemTasks = (
  queueId: number,
  options?: MutationOpts<QueueItemRead, { itemId: number; taskIds: number[] }>
) => {
  const { t } = useTranslation("queues");
  const guildId = useActiveGuildId();
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async ({ itemId, taskIds }: { itemId: number; taskIds: number[] }) => {
      return setQueueItemTasksApiV1GGuildIdQueuesQueueIdItemsItemIdTasksPut(
        guildId,
        queueId,
        itemId,
        taskIds
      ) as unknown as Promise<QueueItemRead>;
    },
    onSuccess: (...args) => {
      void invalidateQueue(queueId);
      void invalidateAllQueues();
      onSuccess?.(...args);
    },
    onError: (...args) => {
      toast.error(t("error"));
      onError?.(...args);
    },
    onSettled,
  });
};

// ── Permission Mutations ────────────────────────────────────────────────────

export const useSetQueuePermissions = (
  queueId: number,
  options?: MutationOpts<QueuePermissionRead[], QueuePermissionCreate[]>
) => {
  const { t } = useTranslation("queues");
  const guildId = useActiveGuildId();
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async (data: QueuePermissionCreate[]) => {
      return setQueuePermissionsApiV1GGuildIdQueuesQueueIdPermissionsPut(
        guildId,
        queueId,
        data
      ) as unknown as Promise<QueuePermissionRead[]>;
    },
    onSuccess: (...args) => {
      void invalidateQueue(queueId);
      void invalidateAllQueues();
      onSuccess?.(...args);
    },
    onError: (...args) => {
      toast.error(t("error"));
      onError?.(...args);
    },
    onSettled,
  });
};

export const useSetQueueRolePermissions = (
  queueId: number,
  options?: MutationOpts<QueueRolePermissionRead[], QueueRolePermissionCreate[]>
) => {
  const { t } = useTranslation("queues");
  const guildId = useActiveGuildId();
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async (data: QueueRolePermissionCreate[]) => {
      return setQueueRolePermissionsApiV1GGuildIdQueuesQueueIdRolePermissionsPut(
        guildId,
        queueId,
        data
      ) as unknown as Promise<QueueRolePermissionRead[]>;
    },
    onSuccess: (...args) => {
      void invalidateQueue(queueId);
      void invalidateAllQueues();
      onSuccess?.(...args);
    },
    onError: (...args) => {
      toast.error(t("error"));
      onError?.(...args);
    },
    onSettled,
  });
};
