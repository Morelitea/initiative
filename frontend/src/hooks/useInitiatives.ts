import { useMutation, useQuery } from "@tanstack/react-query";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";

import type {
  InitiativeCreate,
  InitiativeDirectoryEntry,
  InitiativeJoinRequestCreate,
  InitiativeJoinRequestRead,
  InitiativeRead,
  JoinRequestStatus,
} from "@/api/generated/initiativeAPI.schemas";
import { InitiativeListScope } from "@/api/generated/initiativeAPI.schemas";
import {
  addInitiativeMemberApiV1GGuildIdInitiativesInitiativeIdMembersPost,
  approveJoinRequestApiV1GGuildIdInitiativesInitiativeIdJoinRequestsRequestIdApprovePost,
  createInitiativeApiV1GGuildIdInitiativesPost,
  createJoinRequestApiV1GGuildIdInitiativesInitiativeIdJoinRequestsPost,
  deleteInitiativeApiV1GGuildIdInitiativesInitiativeIdDelete,
  denyJoinRequestApiV1GGuildIdInitiativesInitiativeIdJoinRequestsRequestIdDenyPost,
  getGetInitiativeApiV1GGuildIdInitiativesInitiativeIdGetQueryKey,
  getInitiativeApiV1GGuildIdInitiativesInitiativeIdGet,
  getListInitiativeDirectoryApiV1GGuildIdInitiativesDirectoryGetQueryKey,
  getListInitiativesApiV1GGuildIdInitiativesGetQueryKey,
  getListJoinRequestsApiV1GGuildIdInitiativesInitiativeIdJoinRequestsGetQueryKey,
  joinInitiativeApiV1GGuildIdInitiativesInitiativeIdJoinPost,
  listInitiativeDirectoryApiV1GGuildIdInitiativesDirectoryGet,
  listInitiativesApiV1GGuildIdInitiativesGet,
  listJoinRequestsApiV1GGuildIdInitiativesInitiativeIdJoinRequestsGet,
  removeInitiativeMemberApiV1GGuildIdInitiativesInitiativeIdMembersUserIdDelete,
  updateInitiativeApiV1GGuildIdInitiativesInitiativeIdPatch,
  updateInitiativeMemberApiV1GGuildIdInitiativesInitiativeIdMembersUserIdPatch,
} from "@/api/generated/initiatives/initiatives";
import {
  invalidateAllInitiatives,
  invalidateInitiative,
  invalidateInitiativeJoinRequests,
  invalidateInitiativeMembers,
  invalidateInitiativeMembership,
} from "@/api/query-keys";
import { useActiveGuildId } from "@/hooks/useActiveGuildId";
import { useGuildMutation } from "@/hooks/useApiMutation";
import { toast } from "@/lib/chesterToast";
import { getErrorMessage } from "@/lib/errorMessage";
import type { MutationOpts } from "@/types/mutation";
import type { QueryOpts } from "@/types/query";

// ── Queries ─────────────────────────────────────────────────────────────────

/**
 * The initiatives you are in — the sidebar's list, and every initiative picker.
 *
 * A guild admin is no exception here: their authority still reaches the whole
 * guild, but their navigation is their own memberships. {@link useGuildInitiatives}
 * is the guild-wide listing.
 */
export const useInitiatives = (options?: QueryOpts<InitiativeRead[]>) => {
  const guildId = useActiveGuildId();
  return useQuery<InitiativeRead[]>({
    queryKey: getListInitiativesApiV1GGuildIdInitiativesGetQueryKey(guildId),
    queryFn: () => listInitiativesApiV1GGuildIdInitiativesGet(guildId),
    ...options,
  });
};

const GUILD_SCOPE = { scope: InitiativeListScope.guild } as const;

/**
 * Every initiative in the guild, for the guild-settings management table.
 * Guild admins only — the endpoint answers 403 to anyone else.
 */
export const useGuildInitiatives = (options?: QueryOpts<InitiativeRead[]>) => {
  const guildId = useActiveGuildId();
  return useQuery<InitiativeRead[]>({
    queryKey: getListInitiativesApiV1GGuildIdInitiativesGetQueryKey(guildId, GUILD_SCOPE),
    queryFn: () => listInitiativesApiV1GGuildIdInitiativesGet(guildId, GUILD_SCOPE),
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

/**
 * The guild's initiative directory: what a member may discover and join.
 *
 * Deliberately separate from {@link useInitiatives}, which keeps its contract of
 * "initiatives you are in" — a directory entry carries only what an initiative
 * published about itself (name, colour, description, roster size) plus the
 * caller's own state, never its content.
 */
export const useInitiativeDirectory = (options?: QueryOpts<InitiativeDirectoryEntry[]>) => {
  const guildId = useActiveGuildId();
  const { enabled: userEnabled = true, ...rest } = options ?? {};
  return useQuery<InitiativeDirectoryEntry[]>({
    queryKey: getListInitiativeDirectoryApiV1GGuildIdInitiativesDirectoryGetQueryKey(guildId),
    queryFn: () => listInitiativeDirectoryApiV1GGuildIdInitiativesDirectoryGet(guildId),
    enabled: guildId > 0 && userEnabled,
    ...rest,
  });
};

/**
 * One initiative's join-request queue — who has knocked, and what they said.
 *
 * Manager-only on the server (a plain member has no more business reading who
 * asked to get in than a non-member does), so callers gate the mount on the
 * same standing that gates managing the roster; a stray call answers 403 and
 * the queue simply doesn't render.
 *
 * `status` defaults to the pending rows, which is the queue in the sense that
 * matters: the ones still open to an answer.
 */
export const useInitiativeJoinRequests = (
  initiativeId: number | null,
  params?: { status?: JoinRequestStatus },
  options?: QueryOpts<InitiativeJoinRequestRead[]>
) => {
  const guildId = useActiveGuildId();
  const { enabled: userEnabled = true, ...rest } = options ?? {};
  return useQuery<InitiativeJoinRequestRead[]>({
    queryKey: getListJoinRequestsApiV1GGuildIdInitiativesInitiativeIdJoinRequestsGetQueryKey(
      guildId,
      initiativeId!,
      params
    ),
    queryFn: () =>
      listJoinRequestsApiV1GGuildIdInitiativesInitiativeIdJoinRequestsGet(
        guildId,
        initiativeId!,
        params
      ),
    enabled: guildId > 0 && initiativeId !== null && userEnabled,
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

/**
 * Self-join an `open` initiative from the guild directory.
 *
 * The server decides whether the policy allows it; a refusal comes back as a
 * mapped error code the caller's toast localizes. Success creates an ordinary
 * membership row, so every guild surface has to re-read.
 */
export const useJoinInitiative = (
  options?: MutationOpts<InitiativeRead, { initiativeId: number }>
) =>
  useGuildMutation<InitiativeRead, { initiativeId: number }>(
    {
      mutationFn: (guildId, { initiativeId }) =>
        joinInitiativeApiV1GGuildIdInitiativesInitiativeIdJoinPost(guildId, initiativeId),
      invalidate: () => invalidateInitiativeMembership(),
      errorKey: "initiatives:directory.joinError",
    },
    options
  );

/**
 * Knock on a `request` initiative: ask a manager to let you in.
 *
 * Nothing about what the requester can see changes until someone answers — the
 * only thing that moves is the card's own state, so the directory is what has
 * to re-read (its `has_pending_request`), along with the queue the managers
 * are watching.
 */
export const useRequestToJoinInitiative = (
  options?: MutationOpts<
    InitiativeJoinRequestRead,
    { initiativeId: number; data: InitiativeJoinRequestCreate }
  >
) =>
  useGuildMutation<
    InitiativeJoinRequestRead,
    { initiativeId: number; data: InitiativeJoinRequestCreate }
  >(
    {
      mutationFn: (guildId, { initiativeId, data }) =>
        createJoinRequestApiV1GGuildIdInitiativesInitiativeIdJoinRequestsPost(
          guildId,
          initiativeId,
          data
        ),
      invalidate: (_data, { initiativeId }) =>
        Promise.all([invalidateAllInitiatives(), invalidateInitiativeJoinRequests(initiativeId)]),
      errorKey: "initiatives:joinRequests.requestError",
    },
    options
  );

/**
 * Answer one knock. Approving writes the membership row every join path ends
 * at, so it refreshes as broadly as a self-join does; denying moves only the
 * queue, but both take the same route so a resolved row never lingers in one
 * surface after leaving another.
 */
export const useResolveJoinRequest = (
  options?: MutationOpts<
    InitiativeJoinRequestRead,
    { initiativeId: number; requestId: number; approved: boolean }
  >
) =>
  useGuildMutation<
    InitiativeJoinRequestRead,
    { initiativeId: number; requestId: number; approved: boolean }
  >(
    {
      mutationFn: (guildId, { initiativeId, requestId, approved }) =>
        approved
          ? approveJoinRequestApiV1GGuildIdInitiativesInitiativeIdJoinRequestsRequestIdApprovePost(
              guildId,
              initiativeId,
              requestId
            )
          : denyJoinRequestApiV1GGuildIdInitiativesInitiativeIdJoinRequestsRequestIdDenyPost(
              guildId,
              initiativeId,
              requestId
            ),
      invalidate: (_data, { initiativeId }) =>
        Promise.all([
          invalidateInitiativeMembership(),
          invalidateInitiativeMembers(initiativeId),
          invalidateInitiativeJoinRequests(initiativeId),
        ]),
      errorKey: "initiatives:joinRequests.resolveError",
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
