import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  getListTrashApiV1TrashGetQueryKey,
  listTrashApiV1TrashGet,
  purgeTrashEntityApiV1TrashEntityTypeEntityIdPurgeDelete,
  restoreTrashEntityApiV1TrashEntityTypeEntityIdRestorePost,
} from "@/api/generated/trash/trash";
import type {
  RestoreRequest,
  TrashItemEntityType,
  TrashListResponse,
} from "@/api/generated/initiativeAPI.schemas";
import type { MutationOpts } from "@/types/mutation";
import type { QueryOpts } from "@/types/query";

// ── Queries ─────────────────────────────────────────────────────────────────

export type TrashScope = "mine" | "guild";

export const useTrashList = (
  scope: TrashScope = "mine",
  options?: QueryOpts<TrashListResponse>
) => {
  return useQuery<TrashListResponse>({
    queryKey: getListTrashApiV1TrashGetQueryKey({ scope }),
    queryFn: () => listTrashApiV1TrashGet({ scope }) as unknown as Promise<TrashListResponse>,
    ...options,
  });
};

// ── Mutations ───────────────────────────────────────────────────────────────

// Maps entity_type -> the cache prefix(es) that should be invalidated when a
// row is restored, so the row reappears in active lists across the app
// without requiring an explicit reload.
const ENTITY_INVALIDATION_PREFIXES: Record<TrashItemEntityType, string[]> = {
  project: ["projects"],
  task: ["tasks"],
  document: ["documents"],
  comment: ["comments"],
  initiative: ["initiatives"],
  tag: ["tags"],
  queue: ["queues"],
  queue_item: ["queues"],
  calendar_event: ["calendar-events", "calendarEvents"],
};

export type RestoreTrashVars = {
  entityType: TrashItemEntityType;
  entityId: number;
  body?: RestoreRequest;
};

// 200 "restored" or 200 "needs reassignment" — the dialog branches on
// data.needs_reassignment.
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
    mutationFn: async ({ entityType, entityId, body }: RestoreTrashVars) => {
      return restoreTrashEntityApiV1TrashEntityTypeEntityIdRestorePost(
        entityType,
        entityId,
        body ?? {}
      ) as unknown as Promise<RestoreTrashResponse>;
    },
    onSuccess: (...args) => {
      const [data, variables] = args;
      // Always invalidate the trash list so the row disappears (or stays
      // when the response was needs_reassignment).
      void queryClient.invalidateQueries({ queryKey: ["api", "v1", "trash"] });
      void queryClient.invalidateQueries({
        queryKey: getListTrashApiV1TrashGetQueryKey({ scope: "mine" }),
      });
      void queryClient.invalidateQueries({
        queryKey: getListTrashApiV1TrashGetQueryKey({ scope: "guild" }),
      });
      if ("restored" in data) {
        for (const prefix of ENTITY_INVALIDATION_PREFIXES[variables.entityType] ?? []) {
          void queryClient.invalidateQueries({ queryKey: [prefix] });
        }
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
  entityType: TrashItemEntityType;
  entityId: number;
};

export const usePurgeTrashEntity = (options?: MutationOpts<void, PurgeTrashVars>) => {
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};
  const queryClient = useQueryClient();

  return useMutation({
    ...rest,
    mutationFn: async ({ entityType, entityId }: PurgeTrashVars) => {
      return purgeTrashEntityApiV1TrashEntityTypeEntityIdPurgeDelete(
        entityType,
        entityId
      ) as unknown as Promise<void>;
    },
    onSuccess: (...args) => {
      void queryClient.invalidateQueries({
        queryKey: getListTrashApiV1TrashGetQueryKey({ scope: "mine" }),
      });
      void queryClient.invalidateQueries({
        queryKey: getListTrashApiV1TrashGetQueryKey({ scope: "guild" }),
      });
      onSuccess?.(...args);
    },
    onError: (...args) => {
      onError?.(...args);
    },
    onSettled,
  });
};
