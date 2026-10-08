import type {
  QueueItemCreate,
  QueueItemRead,
  QueueItemUpdate,
  QueueRead,
} from "@/api/generated/initiativeAPI.schemas";
import { SearchEntityType, Tool } from "@/api/generated/initiativeAPI.schemas";
import {
  addQueueItem,
  advanceTurn,
  deleteQueueItem,
  duplicateQueueItem,
  getReadQueueQueryKey,
  holdCurrentTurn,
  previousTurn,
  releaseHeldItem,
  resetQueue,
  setActiveItem,
  startQueue,
  stopQueue,
  updateQueueItem,
} from "@/api/generated/queues/queues";
import { invalidate, q } from "@/api/query-keys";
import { setRelated } from "@/api/relationships";
import { TOOL_HOOKS } from "@/hooks/toolHooks";
import { useCommunityMutation, useOptimisticMutation } from "@/hooks/useApiMutation";
import { idsByKind, type LinkedRef, sameIds } from "@/lib/relationships";
import type { MutationOpts } from "@/types/mutation";

// ── The standard seven ──────────────────────────────────────────────────────
// Built in `toolHooks.ts` from the generated client; see there for the keys
// each one reads and the invalidation each one fires.

const queues = TOOL_HOOKS[Tool.queue];

export const useQueuesList = queues.useList;
export const useQueue = queues.useDetail;
export const useUpdateQueue = queues.useUpdate;
export const useDeleteQueue = queues.useDelete;
export const useSetQueueGrants = queues.useSetGrants;

// ── Item Mutations ──────────────────────────────────────────────────────────

export const useCreateQueueItem = (
  queueId: number,
  options?: MutationOpts<QueueItemRead, QueueItemCreate>
) =>
  useCommunityMutation<QueueItemRead, QueueItemCreate>(
    {
      mutationFn: (communityId, data) => addQueueItem(communityId, queueId, data),
      invalidate: () => invalidate(q.tool(Tool.queue, queueId)),
      errorKey: "queues:error",
    },
    options
  );

export const useUpdateQueueItem = (
  queueId: number,
  options?: MutationOpts<QueueItemRead, { itemId: number; data: QueueItemUpdate }>
) =>
  useCommunityMutation<QueueItemRead, { itemId: number; data: QueueItemUpdate }>(
    {
      mutationFn: (communityId, { itemId, data }) => updateQueueItem(communityId, itemId, data),
      invalidate: () => invalidate(q.tool(Tool.queue, queueId)),
      errorKey: "queues:error",
    },
    options
  );

export const useDeleteQueueItem = (queueId: number, options?: MutationOpts<void, number>) =>
  useCommunityMutation<void, number>(
    {
      mutationFn: (communityId, itemId) => deleteQueueItem(communityId, itemId),
      invalidate: () => invalidate(q.tool(Tool.queue, queueId)),
      errorKey: "queues:error",
    },
    options
  );

export const useDuplicateQueueItem = (
  queueId: number,
  options?: MutationOpts<QueueItemRead, number>
) =>
  useCommunityMutation<QueueItemRead, number>(
    {
      mutationFn: (communityId, itemId) => duplicateQueueItem(communityId, itemId),
      invalidate: () => invalidate(q.tool(Tool.queue, queueId)),
      errorKey: "queues:error",
    },
    options
  );

// ── Turn Control Mutations ──────────────────────────────────────────────────
//
// Turn changes are applied optimistically: the displayed current item and round
// update instantly in the cache, then take the queue the server answers with
// (and the queue WebSocket's refetches). The transition logic below mirrors
// `_visible_items_desc` + advance/previous in `backend/app/services/queues.py`;
// keep the two in sync.

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

  const currentId = queue.current_item_id;
  const startIdx = currentId == null ? -1 : visible.findIndex((item) => item.id === currentId);

  let idx = startIdx;
  let round = queue.current_round;
  let hadStart = startIdx !== -1;
  for (let step = 0; step <= visible.length * 2; step += 1) {
    const nextIdx = (idx + 1) % visible.length;
    if (nextIdx === 0 && hadStart) round += 1;
    const candidate = visible[nextIdx];
    if (candidate.held_at_round === null) {
      return { ...queue, current_item_id: candidate.id, current_round: round };
    }
    if (candidate.held_at_round < round) {
      const released: QueueItemRead = { ...candidate, held_at_round: null };
      return {
        ...queue,
        items: replaceItem(queue, candidate.id, () => released),
        current_item_id: released.id,
        current_round: round,
      };
    }
    // Held and not yet due — skip; subsequent wraps from here bump the round.
    idx = nextIdx;
    hadStart = true;
  }
  // Every rotation item is held and not yet due — clear current.
  return { ...queue, current_item_id: null, current_round: round };
};

/**
 * Step backward through the active rotation. Held items are skipped without
 * auto-release — auto-release is a forward-time effect of advance only.
 */
export const previousQueueState = (queue: QueueRead): QueueRead => {
  const rotation = activeRotationDesc(queue);
  if (rotation.length === 0) return queue;
  const currentId = queue.current_item_id;
  const idx = currentId == null ? -1 : rotation.findIndex((item) => item.id === currentId);
  if (idx <= 0) {
    return {
      ...queue,
      current_item_id: rotation[rotation.length - 1].id,
      current_round: Math.max(1, queue.current_round - 1),
    };
  }
  return { ...queue, current_item_id: rotation[idx - 1].id };
};

export const startQueueState = (queue: QueueRead): QueueRead => {
  const rotation = activeRotationDesc(queue);
  if (rotation.length === 0) return queue;
  return { ...queue, is_active: true, current_item_id: rotation[0].id, current_round: 1 };
};

export const stopQueueState = (queue: QueueRead): QueueRead => ({ ...queue, is_active: false });

export const resetQueueState = (queue: QueueRead): QueueRead => {
  const rotation = activeRotationDesc(queue);
  if (rotation.length === 0) return queue;
  return { ...queue, current_round: 1, current_item_id: rotation[0].id };
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
      current_item_id: cleared.id,
    };
  }
  return { ...queue, current_item_id: target.id };
};

/**
 * Hold the current turn: stamp it with `held_at_round = current_round` and
 * advance to the next rotation slot. If holding empties the rotation,
 * `current_item_id` becomes `null` and `current_round` is unchanged.
 */
export const holdCurrentState = (queue: QueueRead): QueueRead => {
  const currentId = queue.current_item_id;
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
        current_item_id: candidate.id,
        current_round: round,
      };
    }
  }
  // No rotation-eligible item left.
  return { ...queue, items: heldItems, current_item_id: null };
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
 * `current_item_id` is intentionally untouched so releasing doesn't rewind the
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
  const currentId = queue.current_item_id;
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
    current_item_id: promoteToCurrent ? released.id : queue.current_item_id,
  };
};

/**
 * One turn change: applied to the cached queue at once, then replaced by the
 * queue the server answers with. The lists are refetched, and the queue with them.
 */
const useTurn = <TVariables = void>(
  queueId: number,
  send: (communityId: number, variables: TVariables) => Promise<QueueRead>,
  apply: (queue: QueueRead, variables: TVariables) => QueueRead,
  options?: MutationOpts<QueueRead, TVariables>
) =>
  useOptimisticMutation<QueueRead, QueueRead, TVariables>(
    {
      queryKey: (communityId) => getReadQueueQueryKey(communityId, queueId),
      apply,
      seed: (_, queue) => queue,
      mutationFn: send,
      invalidate: () => invalidate(q.allQueues()),
      errorKey: "queues:error",
    },
    options
  );

export const useAdvanceTurn = (queueId: number, options?: MutationOpts<QueueRead, void>) =>
  useTurn(queueId, (communityId) => advanceTurn(communityId, queueId), advanceQueueState, options);

export const usePreviousTurn = (queueId: number, options?: MutationOpts<QueueRead, void>) =>
  useTurn(
    queueId,
    (communityId) => previousTurn(communityId, queueId),
    previousQueueState,
    options
  );

export const useStartQueue = (queueId: number, options?: MutationOpts<QueueRead, void>) =>
  useTurn(queueId, (communityId) => startQueue(communityId, queueId), startQueueState, options);

export const useStopQueue = (queueId: number, options?: MutationOpts<QueueRead, void>) =>
  useTurn(queueId, (communityId) => stopQueue(communityId, queueId), stopQueueState, options);

export const useResetQueue = (queueId: number, options?: MutationOpts<QueueRead, void>) =>
  useTurn(queueId, (communityId) => resetQueue(communityId, queueId), resetQueueState, options);

export const useSetActiveItem = (queueId: number, options?: MutationOpts<QueueRead, number>) =>
  useTurn(
    queueId,
    (communityId, itemId) => setActiveItem(communityId, queueId, itemId),
    setActiveItemState,
    options
  );

export const useHoldCurrent = (queueId: number, options?: MutationOpts<QueueRead, void>) =>
  useTurn(
    queueId,
    (communityId) => holdCurrentTurn(communityId, queueId),
    holdCurrentState,
    options
  );

export interface ReleaseHeldVariables {
  itemId: number;
  /** PF2e Delay: reposition the released item just below current. */
  reposition?: boolean;
}

export const useReleaseHeld = (
  queueId: number,
  options?: MutationOpts<QueueRead, ReleaseHeldVariables>
) =>
  useTurn(
    queueId,
    (communityId, { itemId, reposition }) =>
      releaseHeldItem(communityId, queueId, itemId, { reposition: reposition ?? false }),
    (queue, { itemId, reposition }) => releaseHeldState(queue, itemId, { reposition }),
    options
  );

// ── Item Association Mutations ──────────────────────────────────────────────

/**
 * Set everything a queue item is linked to, whatever kinds those are.
 *
 * This was two hooks, one per kind, and the dialog that called them worked out
 * whether each list had changed by comparing it to the old one **position by
 * position** — so reordering the same files counted as a change and swapping
 * two of them did not.
 *
 * One slice of links is replaced per kind, which is the shape the endpoint is
 * built for. A kind is written only when its set of ids actually differs, and a
 * kind that has lost all its links is written as an empty set rather than
 * skipped — otherwise removing the last file of a kind would not stick.
 */
interface QueueItemLinks {
  itemId: number;
  links: LinkedRef[];
  previous: LinkedRef[];
  /**
   * Write every kind, even one whose set of ids has not moved.
   *
   * For a retry. Skipping the unchanged is an optimisation that assumes the
   * unchanged already landed, and the one case where that is not true is the
   * one being retried: the kind that failed still reads as "no change" against
   * what was asked for the first time.
   */
  force?: boolean;
}

export const useSetQueueItemLinks = (
  queueId: number,
  options?: MutationOpts<void, QueueItemLinks>
) =>
  useCommunityMutation<void, QueueItemLinks>(
    {
      mutationFn: async (communityId, { itemId, links, previous, force }) => {
        const wanted = idsByKind(links);
        const had = idsByKind(previous);

        for (const kind of new Set([...wanted.keys(), ...had.keys()])) {
          const next = wanted.get(kind) ?? [];
          if (!force && sameIds(next, had.get(kind) ?? [])) continue;
          await setRelated(
            communityId,
            { type: SearchEntityType.queue_item, id: itemId },
            kind,
            next
          );
        }
      },
      invalidate: () => invalidate(q.tool(Tool.queue, queueId)),
      errorKey: "queues:error",
    },
    options
  );
