import { useMutation, useQuery } from "@tanstack/react-query";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";

import type { InitiativeCreate, InitiativeRead } from "@/api/generated/initiativeAPI.schemas";
import {
  addInitiativeMemberApiV1GGuildIdInitiativesInitiativeIdMembersPost,
  createInitiativeApiV1GGuildIdInitiativesPost,
  deleteInitiativeApiV1GGuildIdInitiativesInitiativeIdDelete,
  getGetInitiativeApiV1GGuildIdInitiativesInitiativeIdGetQueryKey,
  getInitiativeApiV1GGuildIdInitiativesInitiativeIdGet,
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
import { useGuildMutation } from "@/hooks/useApiMutation";
import { toast } from "@/lib/chesterToast";
import { getErrorMessage } from "@/lib/errorMessage";
import type { MutationOpts } from "@/types/mutation";
import type { QueryOpts } from "@/types/query";

// ── Queries ─────────────────────────────────────────────────────────────────

export const useInitiatives = (options?: QueryOpts<InitiativeRead[]>) => {
  const guildId = useActiveGuildId();
  return useQuery<InitiativeRead[]>({
    queryKey: getListInitiativesApiV1GGuildIdInitiativesGetQueryKey(guildId),
    queryFn: () => listInitiativesApiV1GGuildIdInitiativesGet(guildId),
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
    queryFn: () => listInitiativesApiV1GGuildIdInitiativesGet(guildId!),
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
    queryFn: () => getInitiativeApiV1GGuildIdInitiativesInitiativeIdGet(guildId, initiativeId!),
    enabled: initiativeId !== null && Number.isFinite(initiativeId) && userEnabled,
    ...rest,
  });
};

/**
 * An initiative's display name, resolved from the cached initiatives list —
 * the one lookup every tool breadcrumb uses, since most tool read schemas
 * carry only `initiative_id`, not a nested initiative object. Returns
 * undefined until the id is set and the list has loaded (or for a guild-level
 * entity with no initiative_id, forever — callers treat that as "no crumb").
 */
export const useInitiativeName = (initiativeId: number | null | undefined): string | undefined => {
  const initiativesQuery = useInitiatives({ enabled: initiativeId != null });
  return useMemo(
    () => initiativesQuery.data?.find((initiative) => initiative.id === initiativeId)?.name,
    [initiativesQuery.data, initiativeId]
  );
};

// ── Mutations ───────────────────────────────────────────────────────────────

const invalidateInitiativeMembersAndList = (initiativeId: number) =>
  Promise.all([invalidateInitiativeMembers(initiativeId), invalidateAllInitiatives()]);

export const useCreateInitiative = (options?: MutationOpts<InitiativeRead, InitiativeCreate>) => {
  const { t } = useTranslation("initiatives");
  const guildId = useActiveGuildId();
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    // The generated InitiativeCreate carries one `{plural}_enabled` field per
    // toggleable tool — no hand-maintained field list to drift.
    mutationFn: async (data: InitiativeCreate) => {
      return createInitiativeApiV1GGuildIdInitiativesPost(guildId, data);
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
) =>
  useGuildMutation<
    InitiativeRead,
    {
      initiativeId: number;
      data: Parameters<typeof updateInitiativeApiV1GGuildIdInitiativesInitiativeIdPatch>[2];
    }
  >(
    {
      mutationFn: (guildId, { initiativeId, data }) =>
        updateInitiativeApiV1GGuildIdInitiativesInitiativeIdPatch(guildId, initiativeId, data),
      invalidate: (_data, { initiativeId }) =>
        Promise.all([invalidateAllInitiatives(), invalidateInitiative(initiativeId)]),
      errorKey: "initiatives:settings.updateError",
    },
    options
  );

export const useDeleteInitiative = (options?: MutationOpts<void, number>) =>
  useGuildMutation<void, number>(
    {
      mutationFn: (guildId, initiativeId) =>
        deleteInitiativeApiV1GGuildIdInitiativesInitiativeIdDelete(guildId, initiativeId),
      invalidate: () => invalidateAllInitiatives(),
      errorKey: "initiatives:settings.deleteError",
    },
    options
  );

// Note: the add/update member endpoints return the full updated InitiativeRead
// (roster included), not a single member row — the hooks type what the API
// actually sends.
export const useAddInitiativeMember = (
  options?: MutationOpts<
    InitiativeRead,
    {
      initiativeId: number;
      data: Parameters<
        typeof addInitiativeMemberApiV1GGuildIdInitiativesInitiativeIdMembersPost
      >[2];
    }
  >
) =>
  useGuildMutation<
    InitiativeRead,
    {
      initiativeId: number;
      data: Parameters<
        typeof addInitiativeMemberApiV1GGuildIdInitiativesInitiativeIdMembersPost
      >[2];
    }
  >(
    {
      mutationFn: (guildId, { initiativeId, data }) =>
        addInitiativeMemberApiV1GGuildIdInitiativesInitiativeIdMembersPost(
          guildId,
          initiativeId,
          data
        ),
      invalidate: (_data, { initiativeId }) => invalidateInitiativeMembersAndList(initiativeId),
    },
    options
  );

export const useRemoveInitiativeMember = (
  options?: MutationOpts<void, { initiativeId: number; userId: number }>
) =>
  useGuildMutation<void, { initiativeId: number; userId: number }>(
    {
      mutationFn: async (guildId, { initiativeId, userId }) => {
        await removeInitiativeMemberApiV1GGuildIdInitiativesInitiativeIdMembersUserIdDelete(
          guildId,
          initiativeId,
          userId
        );
      },
      invalidate: (_data, { initiativeId }) => invalidateInitiativeMembersAndList(initiativeId),
    },
    options
  );

export const useUpdateInitiativeMember = (
  options?: MutationOpts<
    InitiativeRead,
    {
      initiativeId: number;
      userId: number;
      data: Parameters<
        typeof updateInitiativeMemberApiV1GGuildIdInitiativesInitiativeIdMembersUserIdPatch
      >[3];
    }
  >
) =>
  useGuildMutation<
    InitiativeRead,
    {
      initiativeId: number;
      userId: number;
      data: Parameters<
        typeof updateInitiativeMemberApiV1GGuildIdInitiativesInitiativeIdMembersUserIdPatch
      >[3];
    }
  >(
    {
      mutationFn: (guildId, { initiativeId, userId, data }) =>
        updateInitiativeMemberApiV1GGuildIdInitiativesInitiativeIdMembersUserIdPatch(
          guildId,
          initiativeId,
          userId,
          data
        ),
      invalidate: (_data, { initiativeId }) => invalidateInitiativeMembersAndList(initiativeId),
    },
    options
  );
