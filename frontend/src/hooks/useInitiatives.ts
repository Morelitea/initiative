import { useMutation, useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";

import type {
  InitiativeMemberRead,
  InitiativeRead,
  UserPublic,
} from "@/api/generated/initiativeAPI.schemas";
import {
  addInitiativeMemberApiV1GGuildIdInitiativesInitiativeIdMembersPost,
  createInitiativeApiV1GGuildIdInitiativesPost,
  deleteInitiativeApiV1GGuildIdInitiativesInitiativeIdDelete,
  getGetInitiativeApiV1GGuildIdInitiativesInitiativeIdGetQueryKey,
  getGetInitiativeMembersApiV1GGuildIdInitiativesInitiativeIdMembersGetQueryKey,
  getInitiativeApiV1GGuildIdInitiativesInitiativeIdGet,
  getInitiativeMembersApiV1GGuildIdInitiativesInitiativeIdMembersGet,
  getListInitiativesApiV1GGuildIdInitiativesGetQueryKey,
  listInitiativesApiV1GGuildIdInitiativesGet,
  removeInitiativeMemberApiV1GGuildIdInitiativesInitiativeIdMembersUserIdDelete,
  updateInitiativeApiV1GGuildIdInitiativesInitiativeIdPatch,
  updateInitiativeMemberApiV1GGuildIdInitiativesInitiativeIdMembersUserIdPatch,
} from "@/api/generated/initiatives/initiatives";
import {
  invalidateAllInitiatives,
  invalidateInitiative,
  invalidateInitiativeMembers,
} from "@/api/query-keys";
import { useActiveGuildId } from "@/hooks/useActiveGuildId";
import { toast } from "@/lib/chesterToast";
import { getErrorMessage } from "@/lib/errorMessage";
import type { MutationOpts } from "@/types/mutation";
import type { QueryOpts } from "@/types/query";

// ── Queries ─────────────────────────────────────────────────────────────────

export const useInitiatives = (options?: QueryOpts<InitiativeRead[]>) => {
  const guildId = useActiveGuildId();
  return useQuery<InitiativeRead[]>({
    queryKey: getListInitiativesApiV1GGuildIdInitiativesGetQueryKey(guildId),
    queryFn: () =>
      listInitiativesApiV1GGuildIdInitiativesGet(guildId) as unknown as Promise<InitiativeRead[]>,
    ...options,
  });
};

/**
 * Fetch initiatives for a specific guild via explicit guild addressing
 * (validated ?guild_id=). Unlike useInitiatives, this does not depend on the
 * user's current guild context — the creation wizards use it from personal
 * pages to list a chosen guild's initiatives.
 */
export const useInitiativesForGuild = (
  guildId: number | null,
  options?: QueryOpts<InitiativeRead[]>
) => {
  const { enabled: userEnabled = true, ...rest } = options ?? {};
  return useQuery<InitiativeRead[]>({
    queryKey: getListInitiativesApiV1GGuildIdInitiativesGetQueryKey(guildId!),
    queryFn: () =>
      listInitiativesApiV1GGuildIdInitiativesGet(guildId!) as unknown as Promise<InitiativeRead[]>,
    enabled: !!guildId && userEnabled,
    ...rest,
  });
};

export const useInitiative = (initiativeId: number | null, options?: QueryOpts<InitiativeRead>) => {
  const guildId = useActiveGuildId();
  const { enabled: userEnabled = true, ...rest } = options ?? {};
  return useQuery<InitiativeRead>({
    queryKey: getGetInitiativeApiV1GGuildIdInitiativesInitiativeIdGetQueryKey(
      guildId,
      initiativeId!
    ),
    queryFn: () =>
      getInitiativeApiV1GGuildIdInitiativesInitiativeIdGet(
        guildId,
        initiativeId!
      ) as unknown as Promise<InitiativeRead>,
    enabled: initiativeId !== null && Number.isFinite(initiativeId) && userEnabled,
    ...rest,
  });
};

export const useInitiativeMembers = (
  initiativeId: number | null,
  options?: QueryOpts<UserPublic[]>
) => {
  const guildId = useActiveGuildId();
  const { enabled: userEnabled = true, ...rest } = options ?? {};
  return useQuery<UserPublic[]>({
    queryKey: getGetInitiativeMembersApiV1GGuildIdInitiativesInitiativeIdMembersGetQueryKey(
      guildId,
      initiativeId!
    ),
    queryFn: () =>
      getInitiativeMembersApiV1GGuildIdInitiativesInitiativeIdMembersGet(
        guildId,
        initiativeId!
      ) as unknown as Promise<UserPublic[]>,
    enabled: initiativeId !== null && Number.isFinite(initiativeId) && userEnabled,
    ...rest,
  });
};

// ── Mutations ───────────────────────────────────────────────────────────────

export const useCreateInitiative = (
  options?: MutationOpts<
    InitiativeRead,
    {
      name: string;
      description?: string;
      color?: string;
      queues_enabled?: boolean;
      events_enabled?: boolean;
      counters_enabled?: boolean;
      advanced_tool_enabled?: boolean;
    }
  >
) => {
  const { t } = useTranslation("initiatives");
  const guildId = useActiveGuildId();
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async (data: {
      name: string;
      description?: string;
      color?: string;
      queues_enabled?: boolean;
      events_enabled?: boolean;
      counters_enabled?: boolean;
      advanced_tool_enabled?: boolean;
    }) => {
      return createInitiativeApiV1GGuildIdInitiativesPost(
        guildId,
        data
      ) as unknown as Promise<InitiativeRead>;
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
      data: Parameters<typeof updateInitiativeApiV1GGuildIdInitiativesInitiativeIdPatch>[2];
    }
  >
) => {
  const guildId = useActiveGuildId();
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async ({
      initiativeId,
      data,
    }: {
      initiativeId: number;
      data: Parameters<typeof updateInitiativeApiV1GGuildIdInitiativesInitiativeIdPatch>[2];
    }) => {
      return updateInitiativeApiV1GGuildIdInitiativesInitiativeIdPatch(
        guildId,
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
  const guildId = useActiveGuildId();
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async (initiativeId: number) => {
      await deleteInitiativeApiV1GGuildIdInitiativesInitiativeIdDelete(guildId, initiativeId);
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
      data: Parameters<
        typeof addInitiativeMemberApiV1GGuildIdInitiativesInitiativeIdMembersPost
      >[2];
    }
  >
) => {
  const guildId = useActiveGuildId();
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async ({
      initiativeId,
      data,
    }: {
      initiativeId: number;
      data: Parameters<
        typeof addInitiativeMemberApiV1GGuildIdInitiativesInitiativeIdMembersPost
      >[2];
    }) => {
      return addInitiativeMemberApiV1GGuildIdInitiativesInitiativeIdMembersPost(
        guildId,
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
  const guildId = useActiveGuildId();
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async ({ initiativeId, userId }: { initiativeId: number; userId: number }) => {
      await removeInitiativeMemberApiV1GGuildIdInitiativesInitiativeIdMembersUserIdDelete(
        guildId,
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
        typeof updateInitiativeMemberApiV1GGuildIdInitiativesInitiativeIdMembersUserIdPatch
      >[3];
    }
  >
) => {
  const guildId = useActiveGuildId();
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
        typeof updateInitiativeMemberApiV1GGuildIdInitiativesInitiativeIdMembersUserIdPatch
      >[3];
    }) => {
      return updateInitiativeMemberApiV1GGuildIdInitiativesInitiativeIdMembersUserIdPatch(
        guildId,
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
