import { keepPreviousData, useMutation, useQuery } from "@tanstack/react-query";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";

import type {
  GetInitiativeMembersParams,
  InitiativeCreate,
  InitiativeDirectoryEntry,
  InitiativeJoinRequestCreate,
  InitiativeJoinRequestRead,
  InitiativeMemberListResponse,
  InitiativeMemberRead,
  InitiativeRead,
  JoinRequestStatus,
} from "@/api/generated/initiativeAPI.schemas";
import { InitiativeListScope } from "@/api/generated/initiativeAPI.schemas";
import {
  addInitiativeMember,
  approveJoinRequest,
  createInitiative,
  createJoinRequest,
  deleteInitiative,
  denyJoinRequest,
  getGetInitiativeMembersQueryKey,
  getGetInitiativeQueryKey,
  getInitiative,
  getInitiativeMembers,
  getListInitiativeDirectoryQueryKey,
  getListInitiativesQueryKey,
  getListJoinRequestsQueryKey,
  joinInitiative,
  listInitiativeDirectory,
  listInitiatives,
  listJoinRequests,
  removeInitiativeMember,
  updateInitiative,
  updateInitiativeMember,
} from "@/api/generated/initiatives/initiatives";
import { invalidate, q } from "@/api/query-keys";
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
    queryKey: getListInitiativesQueryKey(guildId),
    queryFn: () => listInitiatives(guildId),
    ...options,
  });
};

const GUILD_SCOPE = { scope: InitiativeListScope.community } as const;

/**
 * Every initiative in the guild, for the guild-settings management table.
 * Guild admins only — the endpoint answers 403 to anyone else.
 */
export const useGuildInitiatives = (options?: QueryOpts<InitiativeRead[]>) => {
  const guildId = useActiveGuildId();
  return useQuery<InitiativeRead[]>({
    queryKey: getListInitiativesQueryKey(guildId, GUILD_SCOPE),
    queryFn: () => listInitiatives(guildId, GUILD_SCOPE),
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
    queryKey: getListInitiativesQueryKey(guildId!),
    queryFn: () => listInitiatives(guildId!),
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
    queryKey: getListInitiativeDirectoryQueryKey(guildId),
    queryFn: () => listInitiativeDirectory(guildId),
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
    queryKey: getListJoinRequestsQueryKey(guildId, initiativeId!, params),
    queryFn: () => listJoinRequests(guildId, initiativeId!, params),
    enabled: guildId > 0 && initiativeId !== null && userEnabled,
    ...rest,
  });
};

export const useInitiative = (initiativeId: number | null, options?: QueryOpts<InitiativeRead>) => {
  const guildId = useActiveGuildId();
  const { enabled: userEnabled = true, ...rest } = options ?? {};
  return useQuery<InitiativeRead>({
    queryKey: getGetInitiativeQueryKey(guildId, initiativeId!),
    queryFn: () => getInitiative(guildId, initiativeId!),
    enabled: initiativeId !== null && Number.isFinite(initiativeId) && userEnabled,
    ...rest,
  });
};

/**
 * One page of an initiative's roster, each member with their role, searched and
 * paged on the server. A picker wants `useInitiativeMemberSearch` instead: the
 * same people, as the slimmer `UserSummary`.
 */
export const useInitiativeRoster = (
  initiativeId: number | null,
  params: GetInitiativeMembersParams,
  options?: QueryOpts<InitiativeMemberListResponse>
) => {
  const guildId = useActiveGuildId();
  const { enabled: userEnabled = true, ...rest } = options ?? {};
  return useQuery<InitiativeMemberListResponse>({
    queryKey: getGetInitiativeMembersQueryKey(guildId, initiativeId!, params),
    queryFn: () => getInitiativeMembers(guildId, initiativeId!, params),
    enabled: initiativeId !== null && userEnabled,
    // Keep the page on screen while the next one (or the next search) loads.
    placeholderData: keepPreviousData,
    ...rest,
  });
};

/**
 * Every manager of an initiative, read a page at a time until the roster has
 * no more. Managers are few, and a picker that ticks and unticks them needs
 * all of them to know which is which.
 */
export const useInitiativeManagers = (initiativeId: number) => {
  const guildId = useActiveGuildId();
  const params = { is_manager: true, page_size: 100 };
  return useQuery<InitiativeMemberRead[]>({
    queryKey: [...getGetInitiativeMembersQueryKey(guildId, initiativeId, params), "every page"],
    queryFn: async () => {
      const managers = new Map<number, InitiativeMemberRead>();
      let page = 1;
      for (;;) {
        const response = await getInitiativeMembers(guildId, initiativeId, { ...params, page });
        // A page past the end is answered with page 1: the roster changed
        // between reads, so the read starts again from the page served.
        if (response.page !== page) managers.clear();
        for (const manager of response.items) managers.set(manager.user.id, manager);
        if (!response.has_next) return [...managers.values()];
        page = response.page + 1;
      }
    },
  });
};

/**
 * An initiative, resolved from the cached initiatives list — the lookup every
 * tool page header uses for its breadcrumb and its colour, since most tool
 * read schemas carry only `initiative_id`, not a nested initiative object.
 * Returns undefined until the id is set and the list has loaded (or for a
 * guild-level entity with no initiative_id, forever — callers treat that as
 * "no crumb").
 */
export const useListedInitiative = (
  initiativeId: number | null | undefined
): InitiativeRead | undefined => {
  const initiativesQuery = useInitiatives({ enabled: initiativeId != null });
  return useMemo(
    () => initiativesQuery.data?.find((initiative) => initiative.id === initiativeId),
    [initiativesQuery.data, initiativeId]
  );
};

// ── Mutations ───────────────────────────────────────────────────────────────

const invalidateInitiativeMembersAndList = (initiativeId: number) =>
  invalidate(q.initiativeMembers(initiativeId), q.allInitiatives());

export const useCreateInitiative = (options?: MutationOpts<InitiativeRead, InitiativeCreate>) => {
  const { t } = useTranslation("initiatives");
  const guildId = useActiveGuildId();
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    // The generated InitiativeCreate carries one `{plural}_enabled` field per
    // toggleable tool — no hand-maintained field list to drift.
    mutationFn: async (data: InitiativeCreate) => {
      return createInitiative(guildId, data);
    },
    onSuccess: (...args) => {
      toast.success(t("createDialog.created", { name: args[0].name }));
      void invalidate(q.allInitiatives());
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
      data: Parameters<typeof updateInitiative>[2];
    }
  >
) =>
  useGuildMutation<
    InitiativeRead,
    {
      initiativeId: number;
      data: Parameters<typeof updateInitiative>[2];
    }
  >(
    {
      mutationFn: (guildId, { initiativeId, data }) =>
        updateInitiative(guildId, initiativeId, data),
      invalidate: (_data, { initiativeId }) =>
        invalidate(q.allInitiatives(), q.initiative(initiativeId)),
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
      mutationFn: (guildId, { initiativeId }) => joinInitiative(guildId, initiativeId),
      invalidate: () => invalidate(q.guildContent()),
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
        createJoinRequest(guildId, initiativeId, data),
      invalidate: (_data, { initiativeId }) =>
        invalidate(q.allInitiatives(), q.initiativeJoinRequests(initiativeId)),
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
          ? approveJoinRequest(guildId, initiativeId, requestId)
          : denyJoinRequest(guildId, initiativeId, requestId),
      invalidate: (_data, { initiativeId }) =>
        invalidate(
          q.guildContent(),
          q.initiativeMembers(initiativeId),
          q.initiativeJoinRequests(initiativeId)
        ),
      errorKey: "initiatives:joinRequests.resolveError",
    },
    options
  );

export const useDeleteInitiative = (options?: MutationOpts<void, number>) =>
  useGuildMutation<void, number>(
    {
      mutationFn: (guildId, initiativeId) => deleteInitiative(guildId, initiativeId),
      invalidate: () => invalidate(q.allInitiatives()),
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
      data: Parameters<typeof addInitiativeMember>[2];
    }
  >
) =>
  useGuildMutation<
    InitiativeRead,
    {
      initiativeId: number;
      data: Parameters<typeof addInitiativeMember>[2];
    }
  >(
    {
      mutationFn: (guildId, { initiativeId, data }) =>
        addInitiativeMember(guildId, initiativeId, data),
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
        await removeInitiativeMember(guildId, initiativeId, userId);
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
      data: Parameters<typeof updateInitiativeMember>[3];
    }
  >
) =>
  useGuildMutation<
    InitiativeRead,
    {
      initiativeId: number;
      userId: number;
      data: Parameters<typeof updateInitiativeMember>[3];
    }
  >(
    {
      mutationFn: (guildId, { initiativeId, userId, data }) =>
        updateInitiativeMember(guildId, initiativeId, userId, data),
      invalidate: (_data, { initiativeId }) => invalidateInitiativeMembersAndList(initiativeId),
    },
    options
  );
