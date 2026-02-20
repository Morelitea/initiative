import { useMutation, useQuery, type UseQueryOptions } from "@tanstack/react-query";
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
import type { Initiative } from "@/types/api";
import type { InitiativeMemberRead } from "@/api/generated/initiativeAPI.schemas";

type QueryOpts<T> = Omit<UseQueryOptions<T>, "queryKey" | "queryFn">;

// ── Queries ─────────────────────────────────────────────────────────────────

export const useInitiatives = (options?: QueryOpts<Initiative[]>) => {
  return useQuery<Initiative[]>({
    queryKey: getListInitiativesApiV1InitiativesGetQueryKey(),
    queryFn: () => listInitiativesApiV1InitiativesGet() as unknown as Promise<Initiative[]>,
    ...options,
  });
};

export const useInitiative = (initiativeId: number | null, options?: QueryOpts<Initiative>) => {
  const { enabled: userEnabled = true, ...rest } = options ?? {};
  return useQuery<Initiative>({
    queryKey: getGetInitiativeApiV1InitiativesInitiativeIdGetQueryKey(initiativeId!),
    queryFn: () =>
      getInitiativeApiV1InitiativesInitiativeIdGet(initiativeId!) as unknown as Promise<Initiative>,
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

export const useCreateInitiative = () => {
  const { t } = useTranslation("initiatives");

  return useMutation({
    mutationFn: async (data: { name: string; description?: string; color?: string }) => {
      return createInitiativeApiV1InitiativesPost(data) as unknown as Promise<Initiative>;
    },
    onSuccess: (initiative) => {
      toast.success(t("createDialog.created", { name: initiative.name }));
      void invalidateAllInitiatives();
    },
    onError: (error) => {
      toast.error(getErrorMessage(error, "initiatives:createDialog.createError"));
    },
  });
};

export const useUpdateInitiative = () => {
  return useMutation({
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
      ) as unknown as Promise<Initiative>;
    },
    onSuccess: (_data, { initiativeId }) => {
      void invalidateAllInitiatives();
      void invalidateInitiative(initiativeId);
    },
    onError: (error) => {
      toast.error(getErrorMessage(error, "initiatives:settings.updateError"));
    },
  });
};

export const useDeleteInitiative = () => {
  return useMutation({
    mutationFn: async (initiativeId: number) => {
      await deleteInitiativeApiV1InitiativesInitiativeIdDelete(initiativeId);
    },
    onSuccess: () => {
      void invalidateAllInitiatives();
    },
    onError: (error) => {
      toast.error(getErrorMessage(error, "initiatives:settings.deleteError"));
    },
  });
};

export const useAddInitiativeMember = () => {
  return useMutation({
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
    onSuccess: (_data, { initiativeId }) => {
      void invalidateInitiativeMembers(initiativeId);
      void invalidateAllInitiatives();
    },
  });
};

export const useRemoveInitiativeMember = () => {
  return useMutation({
    mutationFn: async ({ initiativeId, userId }: { initiativeId: number; userId: number }) => {
      await removeInitiativeMemberApiV1InitiativesInitiativeIdMembersUserIdDelete(
        initiativeId,
        userId
      );
    },
    onSuccess: (_data, { initiativeId }) => {
      void invalidateInitiativeMembers(initiativeId);
      void invalidateAllInitiatives();
    },
  });
};

export const useUpdateInitiativeMember = () => {
  return useMutation({
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
    onSuccess: (_data, { initiativeId }) => {
      void invalidateInitiativeMembers(initiativeId);
      void invalidateAllInitiatives();
    },
  });
};
