import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import type {
  RestoreRequest,
  TrashItemEntityType,
  TrashListResponse,
} from "@/api/generated/initiativeAPI.schemas";
import {
  getListGuildTrashApiV1GGuildIdTrashGetQueryKey,
  getListMyTrashApiV1MeTrashGetQueryKey,
  listGuildTrashApiV1GGuildIdTrashGet,
  listMyTrashApiV1MeTrashGet,
  purgeTrashEntityApiV1GGuildIdTrashEntityTypeEntityIdPurgeDelete,
  restoreTrashEntityApiV1GGuildIdTrashEntityTypeEntityIdRestorePost,
} from "@/api/generated/trash/trash";
import {
  invalidateAllAdvancedTools,
  invalidateAllCalendarEvents,
  invalidateAllComments,
  invalidateAllCounterGroups,
  invalidateAllDocuments,
  invalidateAllInitiatives,
  invalidateAllProjects,
  invalidateAllQueues,
  invalidateAllTags,
  invalidateAllTasks,
} from "@/api/query-keys";
import { useActiveGuildId } from "@/hooks/useActiveGuildId";
import type { MutationOpts } from "@/types/mutation";
import type { QueryOpts } from "@/types/query";

// ── Queries ─────────────────────────────────────────────────────────────────

/**
 * The current user's own trashed items across every guild they belong to.
 * Powers the personal trash view on the user settings page — user-scoped, no
 * guild context. Restore/purge are addressed per item via its `guild_id`.
 */
export const useMyTrashList = (options?: QueryOpts<TrashListResponse>) =>
  useQuery<TrashListResponse>({
    queryKey: getListMyTrashApiV1MeTrashGetQueryKey(),
    queryFn: () => listMyTrashApiV1MeTrashGet() as unknown as Promise<TrashListResponse>,
    ...options,
  });

/**
 * Everything in the active guild's trash — the guild-admin settings view.
 * Regular members never call this (the backend 403s); they use
 * {@link useMyTrashList} instead.
 */
export const useGuildTrashList = (options?: QueryOpts<TrashListResponse>) => {
  const guildId = useActiveGuildId();
  return useQuery<TrashListResponse>({
    queryKey: getListGuildTrashApiV1GGuildIdTrashGetQueryKey(guildId),
    queryFn: () =>
      listGuildTrashApiV1GGuildIdTrashGet(guildId) as unknown as Promise<TrashListResponse>,
    ...options,
  });
};

// ── Mutations ───────────────────────────────────────────────────────────────

// Maps entity_type -> the shared cache invalidator to run when a row is
// restored, so the row reappears in active lists across the app without an
// explicit reload. Uses the query-keys helpers (predicate-matched against the
// real Orval URL keys — bare string prefixes matched nothing). Child entities
// (task, comment, queue_item, counter) invalidate their parent tool's caches.
const ENTITY_INVALIDATORS: Record<TrashItemEntityType, () => unknown> = {
  project: invalidateAllProjects,
  task: invalidateAllTasks,
  document: invalidateAllDocuments,
  comment: invalidateAllComments,
  initiative: invalidateAllInitiatives,
  tag: invalidateAllTags,
  queue: invalidateAllQueues,
  queue_item: invalidateAllQueues,
  calendar_event: invalidateAllCalendarEvents,
  counter_group: invalidateAllCounterGroups,
  counter: invalidateAllCounterGroups,
  advanced_tool: invalidateAllAdvancedTools,
};

export type RestoreTrashVars = {
  // The item's guild — restore is guild-scoped, and the cross-guild /me view
  // surfaces items from several guilds, so it travels with each row.
  guildId: number;
  entityType: TrashItemEntityType;
  entityId: number;
  body?: RestoreRequest;
};

// 200 {restored: true} or — recovered from a 409 in mutationFn —
// {needs_reassignment: true, ...}. The dialog branches on shape.
export type RestoreTrashResponse =
  | { restored: true }
  | { needs_reassignment: true; valid_owner_ids: number[]; detail: string };

export const useRestoreTrashEntity = (
  options?: MutationOpts<RestoreTrashResponse, RestoreTrashVars>
) => {
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};
  const queryClient = useQueryClient();

  return useMutation({
    ...rest,
    mutationFn: async ({ guildId, entityType, entityId, body }: RestoreTrashVars) => {
      try {
        return (await restoreTrashEntityApiV1GGuildIdTrashEntityTypeEntityIdRestorePost(
          guildId,
          entityType,
          entityId,
          body ?? {}
        )) as unknown as RestoreTrashResponse;
      } catch (err) {
        // The needs-reassignment branch is a successful interaction shape
        // (the user just needs to pick an owner) but the API correctly
        // signals it as 409 so non-React-Query consumers don't mistake it
        // for a happy path. Recover the body and let onSuccess handle it.
        const status = (err as { response?: { status?: number; data?: unknown } })?.response
          ?.status;
        const data = (err as { response?: { status?: number; data?: unknown } })?.response?.data;
        if (
          status === 409 &&
          data &&
          typeof data === "object" &&
          "needs_reassignment" in (data as object)
        ) {
          return data as RestoreTrashResponse;
        }
        throw err;
      }
    },
    onSuccess: (...args) => {
      const [data, variables] = args;
      // Always invalidate both trash views (personal /me and the item's guild)
      // so the row disappears — or stays, when the response was
      // needs_reassignment.
      void queryClient.invalidateQueries({ queryKey: getListMyTrashApiV1MeTrashGetQueryKey() });
      void queryClient.invalidateQueries({
        queryKey: getListGuildTrashApiV1GGuildIdTrashGetQueryKey(variables.guildId),
      });
      if ("restored" in data) {
        void ENTITY_INVALIDATORS[variables.entityType]?.();
      }
      onSuccess?.(...args);
    },
    onError: (...args) => {
      onError?.(...args);
    },
    onSettled,
  });
};

export type PurgeTrashVars = {
  // Purge is guild-scoped + admin-only; only reachable from the guild view,
  // but it still travels with the row for consistency with restore.
  guildId: number;
  entityType: TrashItemEntityType;
  entityId: number;
};

export const usePurgeTrashEntity = (options?: MutationOpts<void, PurgeTrashVars>) => {
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};
  const queryClient = useQueryClient();

  return useMutation({
    ...rest,
    mutationFn: async ({ guildId, entityType, entityId }: PurgeTrashVars) => {
      return purgeTrashEntityApiV1GGuildIdTrashEntityTypeEntityIdPurgeDelete(
        guildId,
        entityType,
        entityId
      ) as unknown as Promise<void>;
    },
    onSuccess: (...args) => {
      const [, variables] = args;
      void queryClient.invalidateQueries({ queryKey: getListMyTrashApiV1MeTrashGetQueryKey() });
      void queryClient.invalidateQueries({
        queryKey: getListGuildTrashApiV1GGuildIdTrashGetQueryKey(variables.guildId),
      });
      onSuccess?.(...args);
    },
    onError: (...args) => {
      onError?.(...args);
    },
    onSettled,
  });
};
