import { useMutation, useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import {
  listInitiativesApiV1InitiativesGet,
  getListInitiativesApiV1InitiativesGetQueryKey,
  getInitiativeApiV1InitiativesInitiativeIdGet,
  getGetInitiativeApiV1InitiativesInitiativeIdGetQueryKey,
  createInitiativeApiV1InitiativesPost,
  updateInitiativeApiV1InitiativesInitiativeIdPatch,
  deleteInitiativeApiV1InitiativesInitiativeIdDelete,
  getInitiativeMembersApiV1InitiativesInitiativeIdMembersGet,
  getGetInitiativeMembersApiV1InitiativesInitiativeIdMembersGetQueryKey,
  addInitiativeMemberApiV1InitiativesInitiativeIdMembersPost,
  removeInitiativeMemberApiV1InitiativesInitiativeIdMembersUserIdDelete,
  updateInitiativeMemberApiV1InitiativesInitiativeIdMembersUserIdPatch,
} from "@/api/generated/initiatives/initiatives";
import {
  invalidateAllInitiatives,
  invalidateInitiative,
  invalidateInitiativeMembers,
} from "@/api/query-keys";
import { getErrorMessage } from "@/lib/errorMessage";
import type { InitiativeMemberRead, InitiativeRead } from "@/api/generated/initiativeAPI.schemas";
import type { MutationOpts } from "@/types/mutation";
import type { QueryOpts } from "@/types/query";

// ── Queries ─────────────────────────────────────────────────────────────────

export const useInitiatives = (options?: QueryOpts<InitiativeRead[]>) => {
  return useQuery<InitiativeRead[]>({
    queryKey: getListInitiativesApiV1InitiativesGetQueryKey(),
    queryFn: () => listInitiativesApiV1InitiativesGet() as unknown as Promise<InitiativeRead[]>,
    ...options,
  });
};

export const useInitiative = (initiativeId: number | null, options?: QueryOpts<InitiativeRead>) => {
  const { enabled: userEnabled = true, ...rest } = options ?? {};
  return useQuery<InitiativeRead>({
    queryKey: getGetInitiativeApiV1InitiativesInitiativeIdGetQueryKey(initiativeId!),
    queryFn: () =>
      getInitiativeApiV1InitiativesInitiativeIdGet(
        initiativeId!
      ) as unknown as Promise<InitiativeRead>,
    enabled: initiativeId !== null && Number.isFinite(initiativeId) && userEnabled,
    ...rest,
  });
};

export const useInitiativeMembers = (
  initiativeId: number | null,
  options?: QueryOpts<InitiativeMemberRead[]>
) => {
  const { enabled: userEnabled = true, ...rest } = options ?? {};
  return useQuery<InitiativeMemberRead[]>({
    queryKey: getGetInitiativeMembersApiV1InitiativesInitiativeIdMembersGetQueryKey(initiativeId!),
    queryFn: () =>
      getInitiativeMembersApiV1InitiativesInitiativeIdMembersGet(
        initiativeId!
      ) as unknown as Promise<InitiativeMemberRead[]>,
    enabled: initiativeId !== null && Number.isFinite(initiativeId) && userEnabled,
    ...rest,
  });
};

// ── Mutations ───────────────────────────────────────────────────────────────

export const useCreateInitiative = (
  options?: MutationOpts<InitiativeRead, { name: string; description?: string; color?: string }>
) => {
  const { t } = useTranslation("initiatives");
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async (data: { name: string; description?: string; color?: string }) => {
      return createInitiativeApiV1InitiativesPost(data) as unknown as Promise<InitiativeRead>;
    },
    onSuccess: (...args) => {
      toast.success(t("createDialog.created", { name: args[0].name }));
      void invalidateAllInitiatives();
      onSuccess?.(...args);
    },
    onError: (...args) => {
      toast.error(getErrorMessage(args[0], "initiatives:createDialog.createError"));
      onError?.(...args);
    },
    onSettled,
  });
};

export const useUpdateInitiative = (
  options?: MutationOpts<
    InitiativeRead,
    {
      initiativeId: number;
      data: Parameters<typeof updateInitiativeApiV1InitiativesInitiativeIdPatch>[1];
    }
  >
) => {
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async ({
      initiativeId,
      data,
    }: {
      initiativeId: number;
      data: Parameters<typeof updateInitiativeApiV1InitiativesInitiativeIdPatch>[1];
    }) => {
      return updateInitiativeApiV1InitiativesInitiativeIdPatch(
        initiativeId,
        data
      ) as unknown as Promise<InitiativeRead>;
    },
    onSuccess: (...args) => {
      void invalidateAllInitiatives();
      void invalidateInitiative(args[1].initiativeId);
      onSuccess?.(...args);
    },
    onError: (...args) => {
      toast.error(getErrorMessage(args[0], "initiatives:settings.updateError"));
      onError?.(...args);
    },
    onSettled,
  });
};

export const useDeleteInitiative = (options?: MutationOpts<void, number>) => {
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async (initiativeId: number) => {
      await deleteInitiativeApiV1InitiativesInitiativeIdDelete(initiativeId);
    },
    onSuccess: (...args) => {
      void invalidateAllInitiatives();
      onSuccess?.(...args);
    },
    onError: (...args) => {
      toast.error(getErrorMessage(args[0], "initiatives:settings.deleteError"));
      onError?.(...args);
    },
    onSettled,
  });
};

export const useAddInitiativeMember = (
  options?: MutationOpts<
    InitiativeMemberRead,
    {
      initiativeId: number;
      data: Parameters<typeof addInitiativeMemberApiV1InitiativesInitiativeIdMembersPost>[1];
    }
  >
) => {
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async ({
      initiativeId,
      data,
    }: {
      initiativeId: number;
      data: Parameters<typeof addInitiativeMemberApiV1InitiativesInitiativeIdMembersPost>[1];
    }) => {
      return addInitiativeMemberApiV1InitiativesInitiativeIdMembersPost(
        initiativeId,
        data
      ) as unknown as Promise<InitiativeMemberRead>;
    },
    onSuccess: (...args) => {
      void invalidateInitiativeMembers(args[1].initiativeId);
      void invalidateAllInitiatives();
      onSuccess?.(...args);
    },
    onError,
    onSettled,
  });
};

export const useRemoveInitiativeMember = (
  options?: MutationOpts<void, { initiativeId: number; userId: number }>
) => {
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async ({ initiativeId, userId }: { initiativeId: number; userId: number }) => {
      await removeInitiativeMemberApiV1InitiativesInitiativeIdMembersUserIdDelete(
        initiativeId,
        userId
      );
    },
    onSuccess: (...args) => {
      void invalidateInitiativeMembers(args[1].initiativeId);
      void invalidateAllInitiatives();
      onSuccess?.(...args);
    },
    onError,
    onSettled,
  });
};

export const useUpdateInitiativeMember = (
  options?: MutationOpts<
    InitiativeMemberRead,
    {
      initiativeId: number;
      userId: number;
      data: Parameters<
        typeof updateInitiativeMemberApiV1InitiativesInitiativeIdMembersUserIdPatch
      >[2];
    }
  >
) => {
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async ({
      initiativeId,
      userId,
      data,
    }: {
      initiativeId: number;
      userId: number;
      data: Parameters<
        typeof updateInitiativeMemberApiV1InitiativesInitiativeIdMembersUserIdPatch
      >[2];
    }) => {
      return updateInitiativeMemberApiV1InitiativesInitiativeIdMembersUserIdPatch(
        initiativeId,
        userId,
        data
      ) as unknown as Promise<InitiativeMemberRead>;
    },
    onSuccess: (...args) => {
      void invalidateInitiativeMembers(args[1].initiativeId);
      void invalidateAllInitiatives();
      onSuccess?.(...args);
    },
    onError,
    onSettled,
  });
};
