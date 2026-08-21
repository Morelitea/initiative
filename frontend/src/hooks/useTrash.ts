import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import type {
  EntityType,
  RestoreResponse,
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
  invalidateAllCalendarEvents,
  invalidateAllCalendars,
  invalidateAllComments,
  invalidateAllCounterGroups,
  invalidateAllDashboards,
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
    queryFn: () => listMyTrashApiV1MeTrashGet(),
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
    queryFn: () => listGuildTrashApiV1GGuildIdTrashGet(guildId),
    ...options,
  });
};

// ── Mutations ───────────────────────────────────────────────────────────────

// Maps entity_type -> the shared cache invalidator to run when a row is
// restored, so the row reappears in active lists across the app without an
// explicit reload. Uses the query-keys helpers (predicate-matched against the
// real Orval URL keys — bare string prefixes matched nothing). Child entities
// (task, comment, queue_item, counter) invalidate their parent tool's caches.
const ENTITY_INVALIDATORS: Record<EntityType, () => unknown> = {
  project: invalidateAllProjects,
  task: invalidateAllTasks,
  document: invalidateAllDocuments,
  comment: invalidateAllComments,
  initiative: invalidateAllInitiatives,
  tag: invalidateAllTags,
  queue: invalidateAllQueues,
  queue_item: invalidateAllQueues,
  calendar: invalidateAllCalendars,
  calendar_event: invalidateAllCalendarEvents,
  counter_group: invalidateAllCounterGroups,
  counter: invalidateAllCounterGroups,
  dashboard: invalidateAllDashboards,
};

export type RestoreTrashVars = {
  // The item's guild — restore is guild-scoped, and the cross-guild /me view
  // surfaces items from several guilds, so it travels with each row.
  guildId: number;
  entityType: EntityType;
  entityId: number;
};

export const useRestoreTrashEntity = (
  options?: MutationOpts<RestoreResponse, RestoreTrashVars>
) => {
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};
  const queryClient = useQueryClient();

  return useMutation({
    ...rest,
    mutationFn: async ({
      guildId,
      entityType,
      entityId,
    }: RestoreTrashVars): Promise<RestoreResponse> =>
      restoreTrashEntityApiV1GGuildIdTrashEntityTypeEntityIdRestorePost(
        guildId,
        entityType,
        entityId
      ),
    onSuccess: (...args) => {
      const [, variables] = args;
      // Invalidate both trash views (personal /me and the item's guild) so the
      // restored row disappears from each.
      void queryClient.invalidateQueries({ queryKey: getListMyTrashApiV1MeTrashGetQueryKey() });
      void queryClient.invalidateQueries({
        queryKey: getListGuildTrashApiV1GGuildIdTrashGetQueryKey(variables.guildId),
      });
      void ENTITY_INVALIDATORS[variables.entityType]?.();
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
  entityType: EntityType;
  entityId: number;
};

export const usePurgeTrashEntity = (options?: MutationOpts<void, PurgeTrashVars>) => {
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};
  const queryClient = useQueryClient();

  return useMutation({
    ...rest,
    mutationFn: async ({ guildId, entityType, entityId }: PurgeTrashVars) => {
      await purgeTrashEntityApiV1GGuildIdTrashEntityTypeEntityIdPurgeDelete(
        guildId,
        entityType,
        entityId
      );
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
