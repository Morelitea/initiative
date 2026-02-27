import { keepPreviousData, useMutation, useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import {
  listQueuesApiV1QueuesGet,
  getListQueuesApiV1QueuesGetQueryKey,
  readQueueApiV1QueuesQueueIdGet,
  getReadQueueApiV1QueuesQueueIdGetQueryKey,
  createQueueApiV1QueuesPost,
  updateQueueApiV1QueuesQueueIdPatch,
  deleteQueueApiV1QueuesQueueIdDelete,
  addQueueItemApiV1QueuesQueueIdItemsPost,
  updateQueueItemApiV1QueuesQueueIdItemsItemIdPatch,
  deleteQueueItemApiV1QueuesQueueIdItemsItemIdDelete,
  reorderQueueItemsApiV1QueuesQueueIdItemsReorderPut,
  advanceTurnApiV1QueuesQueueIdNextPost,
  previousTurnApiV1QueuesQueueIdPreviousPost,
  startQueueApiV1QueuesQueueIdStartPost,
  stopQueueApiV1QueuesQueueIdStopPost,
  resetQueueApiV1QueuesQueueIdResetPost,
  setActiveItemApiV1QueuesQueueIdSetActiveItemIdPost,
  setQueueItemTagsApiV1QueuesQueueIdItemsItemIdTagsPut,
  setQueueItemDocumentsApiV1QueuesQueueIdItemsItemIdDocumentsPut,
  setQueueItemTasksApiV1QueuesQueueIdItemsItemIdTasksPut,
  setQueuePermissionsApiV1QueuesQueueIdPermissionsPut,
  setQueueRolePermissionsApiV1QueuesQueueIdRolePermissionsPut,
} from "@/api/generated/queues/queues";
import { invalidateAllQueues, invalidateQueue } from "@/api/query-keys";
import type {
  ListQueuesApiV1QueuesGetParams,
  QueueCreate,
  QueueItemCreate,
  QueueItemReorderRequest,
  QueueItemUpdate,
  QueueListResponse,
  QueueRead,
  QueueItemRead,
  QueueUpdate,
  QueuePermissionCreate,
  QueuePermissionRead,
  QueueRolePermissionCreate,
  QueueRolePermissionRead,
} from "@/api/generated/initiativeAPI.schemas";
import type { MutationOpts } from "@/types/mutation";
import type { QueryOpts } from "@/types/query";

// ── Queries ─────────────────────────────────────────────────────────────────

export const useQueuesList = (
  params: ListQueuesApiV1QueuesGetParams,
  options?: QueryOpts<QueueListResponse>
) => {
  return useQuery<QueueListResponse>({
    queryKey: getListQueuesApiV1QueuesGetQueryKey(params),
    queryFn: () => listQueuesApiV1QueuesGet(params) as unknown as Promise<QueueListResponse>,
    placeholderData: keepPreviousData,
    ...options,
  });
};

export const useQueue = (queueId: number | null, options?: QueryOpts<QueueRead>) => {
  const { enabled: userEnabled = true, ...rest } = options ?? {};
  return useQuery<QueueRead>({
    queryKey: getReadQueueApiV1QueuesQueueIdGetQueryKey(queueId!),
    queryFn: () => readQueueApiV1QueuesQueueIdGet(queueId!) as unknown as Promise<QueueRead>,
    enabled: queueId !== null && Number.isFinite(queueId) && userEnabled,
    ...rest,
  });
};

// ── Mutations ───────────────────────────────────────────────────────────────

export const useCreateQueue = (options?: MutationOpts<QueueRead, QueueCreate>) => {
  const { t } = useTranslation("queues");
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async (data: QueueCreate) => {
      return createQueueApiV1QueuesPost(data) as unknown as Promise<QueueRead>;
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
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async (data: QueueUpdate) => {
      return updateQueueApiV1QueuesQueueIdPatch(queueId, data) as unknown as Promise<QueueRead>;
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
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async (queueId: number) => {
      await deleteQueueApiV1QueuesQueueIdDelete(queueId);
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
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async (data: QueueItemCreate) => {
      return addQueueItemApiV1QueuesQueueIdItemsPost(
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
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async ({ itemId, data }: { itemId: number; data: QueueItemUpdate }) => {
      return updateQueueItemApiV1QueuesQueueIdItemsItemIdPatch(
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
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async (itemId: number) => {
      await deleteQueueItemApiV1QueuesQueueIdItemsItemIdDelete(queueId, itemId);
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
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async (data: QueueItemReorderRequest) => {
      return reorderQueueItemsApiV1QueuesQueueIdItemsReorderPut(
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

export const useAdvanceTurn = (queueId: number, options?: MutationOpts<QueueRead, void>) => {
  const { t } = useTranslation("queues");
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async () => {
      return advanceTurnApiV1QueuesQueueIdNextPost(queueId) as unknown as Promise<QueueRead>;
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

export const usePreviousTurn = (queueId: number, options?: MutationOpts<QueueRead, void>) => {
  const { t } = useTranslation("queues");
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async () => {
      return previousTurnApiV1QueuesQueueIdPreviousPost(queueId) as unknown as Promise<QueueRead>;
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

export const useStartQueue = (queueId: number, options?: MutationOpts<QueueRead, void>) => {
  const { t } = useTranslation("queues");
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async () => {
      return startQueueApiV1QueuesQueueIdStartPost(queueId) as unknown as Promise<QueueRead>;
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

export const useStopQueue = (queueId: number, options?: MutationOpts<QueueRead, void>) => {
  const { t } = useTranslation("queues");
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async () => {
      return stopQueueApiV1QueuesQueueIdStopPost(queueId) as unknown as Promise<QueueRead>;
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

export const useResetQueue = (queueId: number, options?: MutationOpts<QueueRead, void>) => {
  const { t } = useTranslation("queues");
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async () => {
      return resetQueueApiV1QueuesQueueIdResetPost(queueId) as unknown as Promise<QueueRead>;
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

export const useSetActiveItem = (queueId: number, options?: MutationOpts<QueueRead, number>) => {
  const { t } = useTranslation("queues");
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async (itemId: number) => {
      return setActiveItemApiV1QueuesQueueIdSetActiveItemIdPost(
        queueId,
        itemId
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

// ── Item Association Mutations ──────────────────────────────────────────────

export const useSetQueueItemTags = (
  queueId: number,
  options?: MutationOpts<QueueItemRead, { itemId: number; tagIds: number[] }>
) => {
  const { t } = useTranslation("queues");
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async ({ itemId, tagIds }: { itemId: number; tagIds: number[] }) => {
      return setQueueItemTagsApiV1QueuesQueueIdItemsItemIdTagsPut(
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
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async ({ itemId, documentIds }: { itemId: number; documentIds: number[] }) => {
      return setQueueItemDocumentsApiV1QueuesQueueIdItemsItemIdDocumentsPut(
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
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async ({ itemId, taskIds }: { itemId: number; taskIds: number[] }) => {
      return setQueueItemTasksApiV1QueuesQueueIdItemsItemIdTasksPut(
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
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async (data: QueuePermissionCreate[]) => {
      return setQueuePermissionsApiV1QueuesQueueIdPermissionsPut(
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
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async (data: QueueRolePermissionCreate[]) => {
      return setQueueRolePermissionsApiV1QueuesQueueIdRolePermissionsPut(
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
