import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/react-query";

import { updateGuildMembershipApiV1CommunitiesGuildIdMembersUserIdPatch } from "@/api/generated/communities/communities";
import type {
  AccountDeletionRequest,
  AccountDeletionResponse,
  ExportUsersCsvApiV1CGuildIdUsersExportCsvGetParams,
  GuildRole,
  Tool,
  UserGuildMember,
  UserGuildRead,
  UserRead,
  UserSummary,
} from "@/api/generated/initiativeAPI.schemas";
import { useSearchInitiativeMembersApiV1CGuildIdInitiativesInitiativeIdMembersSearchGet } from "@/api/generated/initiatives/initiatives";
import {
  approveUserApiV1CGuildIdUsersUserIdApprovePost,
  deleteOwnAccountApiV1UsersMeDeleteAccountPost,
  exportUsersCsvApiV1CGuildIdUsersExportCsvGet,
  getListDecorationPacksApiV1UsersMeDecorationPacksGetQueryKey,
  getListMyDecorationsApiV1UsersMeDecorationsGetQueryKey,
  getListUsersApiV1CGuildIdUsersGetQueryKey,
  installDecorationPackApiV1UsersMeDecorationPacksUidPost,
  listUsersApiV1CGuildIdUsersGet,
  removeDecorationPackApiV1UsersMeDecorationPacksUidDelete,
  updateUsersMeApiV1UsersMePatch,
  useListDecorationPacksApiV1UsersMeDecorationPacksGet,
  useListMyDecorationsApiV1UsersMeDecorationsGet,
  useReadUserCommunitiesApiV1UsersHandleCommunitiesGet,
  useReadUserProfileApiV1UsersHandleProfileGet,
  useSearchUsersApiV1CGuildIdUsersSearchGet,
} from "@/api/generated/users/users";
import { invalidate, q } from "@/api/query-keys";
import { useActiveGuildId } from "@/hooks/useActiveGuildId";
import { useApiMutation, useGuildMutation } from "@/hooks/useApiMutation";
import { downloadBlob } from "@/lib/csv";
import type { MutationOpts } from "@/types/mutation";
import type { QueryOpts } from "@/types/query";

// ── Queries ─────────────────────────────────────────────────────────────────

/**
 * Members of a guild. Defaults to the active guild; pass `guildIdOverride` to
 * read a specific guild's members from a cross-guild surface (e.g. the personal
 * trash view reassigning an item that lives in another guild).
 */
export const useUsers = (options?: QueryOpts<UserGuildMember[]>, guildIdOverride?: number) => {
  const activeGuildId = useActiveGuildId();
  const guildId = guildIdOverride ?? activeGuildId;
  return useQuery<UserGuildMember[]>({
    queryKey: getListUsersApiV1CGuildIdUsersGetQueryKey(guildId),
    queryFn: () => listUsersApiV1CGuildIdUsersGet(guildId),
    ...options,
  });
};

/** Default page size for slim member typeaheads — mirrors the CommandCenter
 *  task search (a bounded dropdown-sized window, not the whole roster). */
export const USER_SEARCH_PAGE_SIZE = 25;

/** Server-side ceiling on one request's `userIds` list — mirrors
 *  `MAX_ID_FILTER_VALUES` in `backend/app/db/query.py`. */
export const USER_ID_LOOKUP_MAX = 100;

export interface UserSearchOptions {
  /** Matches a member's name — by what it contains, and by how close it is, so
   *  a name typed nearly right still finds the person. */
  search?: string;
  /** Which page of the match to read. Defaults to the first, which is all a
   *  typeahead ever wants; the search page reads further. */
  page?: number;
  /** Resolve these specific members instead of browsing the roster — how a
   *  picker turns stored ids back into names/avatars. Narrows the same scoped
   *  set, so an id outside it simply doesn't come back. */
  userIds?: number[];
  /** Bounded page size (server caps at 100). */
  pageSize?: number;
  /** Only the people who can open this row: who may be named on what it
   *  holds (assignees, attendees, person properties, queue items). */
  canOpen?: { tool: Tool; id: number | null | undefined };
  /** Gate the request — pass the picker's `open` state so we don't fetch until
   *  the dropdown is shown. */
  enabled?: boolean;
  /** Read a specific guild instead of the active one (cross-guild surfaces). */
  guildIdOverride?: number;
}

/** Shared query params for the three slim member-search endpoints. */
const memberSearchParams = (search: string | undefined, userIds: number[] | undefined) => ({
  search: search?.trim() || undefined,
  user_id: userIds?.length ? userIds.slice(0, USER_ID_LOOKUP_MAX) : undefined,
});

/**
 * One person's profile, by their handle as it appears in a URL
 * (``jordan1234`` — see ``getUrlHandle``).
 *
 * Public and community-independent: the same page whoever opens it, so there
 * is no guild in the call.
 */
/**
 * The listed communities one person belongs to.
 *
 * Its own read rather than part of the profile: the profile is the public
 * projection of the account row, and this is about guilds. It also changes far
 * more slowly than a status or a presence dot, so it is held longer.
 */
export const useUserCommunities = (handle: string | null | undefined) =>
  useReadUserCommunitiesApiV1UsersHandleCommunitiesGet(handle as string, {
    query: { enabled: Boolean(handle), staleTime: 5 * 60_000 },
  });

export const useUserProfile = (handle: string | null | undefined) =>
  useReadUserProfileApiV1UsersHandleProfileGet(handle as string, {
    query: {
      enabled: Boolean(handle),
      // A profile changes without the reader doing anything — the subject
      // signs off, edits their status, changes what they are wearing — and
      // this page is outside the community tree, so no realtime socket is
      // going to tell it. Nor does the app refetch on focus. So it asks again
      // on a timer, which pauses while the tab is in the background.
      staleTime: 30_000,
      refetchInterval: 60_000,
    },
  });

/**
 * The decoration store: every pack this build ships, and which you have.
 *
 * The catalog is fixed per build and the answer changes only when you take or
 * give back a pack, so it is held until a mutation says otherwise.
 */
export const useDecorationPacks = () =>
  useListDecorationPacksApiV1UsersMeDecorationPacksGet({
    query: { staleTime: 5 * 60_000 },
  });

/** Taking a pack, and giving one back. Both change what the pickers may offer
 *  and what the profile is wearing, so both refresh all three. */
const useDecorationPackMutation = (
  run: (packId: string) => Promise<unknown>,
  options?: MutationOpts<unknown, string>
) => {
  const queryClient = useQueryClient();
  return useApiMutation<unknown, string>(
    {
      mutationFn: run,
      invalidate: () => {
        void queryClient.invalidateQueries({
          queryKey: getListDecorationPacksApiV1UsersMeDecorationPacksGetQueryKey(),
        });
        void queryClient.invalidateQueries({
          queryKey: getListMyDecorationsApiV1UsersMeDecorationsGetQueryKey(),
        });
        // Giving a pack back can take pieces off the profile server-side, so
        // the account the form reads from has changed too.
        void invalidate(q.currentUser());
      },
    },
    options
  );
};

export const useInstallDecorationPack = (options?: MutationOpts<unknown, string>) =>
  useDecorationPackMutation(
    (packId) => installDecorationPackApiV1UsersMeDecorationPacksUidPost(packId),
    options
  );

export const useRemoveDecorationPack = (options?: MutationOpts<unknown, string>) =>
  useDecorationPackMutation(
    (packId) => removeDecorationPackApiV1UsersMeDecorationPacksUidDelete(packId),
    options
  );

/**
 * What the signed-in account may dress its profile in — what ships with the
 * app plus whatever it has acquired. Drives the pickers on Settings > Profile;
 * a library changes only when a pack is installed, so it is held a good while.
 */
export const useMyDecorations = () =>
  useListMyDecorationsApiV1UsersMeDecorationsGet({
    query: { staleTime: 5 * 60_000 },
  });

/**
 * Slim, server-side member typeahead for the active guild. Returns
 * {@link UserSummary} rows (id, name, avatar, status) for a bounded page —
 * the replacement for loading the whole roster via {@link useUsers} and
 * filtering client-side. Debounce the `search` value at the call site.
 */
export const useUserSearch = ({
  search,
  page,
  userIds,
  pageSize = USER_SEARCH_PAGE_SIZE,
  enabled = true,
  guildIdOverride,
  canOpen,
}: UserSearchOptions = {}) => {
  const activeGuildId = useActiveGuildId();
  const guildId = guildIdOverride ?? activeGuildId;
  return useSearchUsersApiV1CGuildIdUsersSearchGet(
    guildId,
    {
      ...memberSearchParams(search, userIds),
      page_size: pageSize,
      ...(page != null ? { page } : {}),
      ...(canOpen ? { tool: canOpen.tool, resource_id: canOpen.id } : {}),
    },
    {
      query: {
        enabled: enabled && guildId != null && (!canOpen || canOpen.id != null),
        staleTime: 30_000,
        // Keep the prior page visible while the next keystroke's request is in
        // flight so the dropdown doesn't flash empty on every character.
        placeholderData: keepPreviousData,
      },
    }
  );
};

/**
 * Slim, server-side typeahead over one initiative's members — same shape as
 * {@link useUserSearch} but scoped to `initiativeId` (assignee/linked-member
 * pickers that must not offer users outside the initiative).
 */
export const useInitiativeMemberSearch = (
  initiativeId: number | null | undefined,
  {
    search,
    userIds,
    pageSize = USER_SEARCH_PAGE_SIZE,
    enabled = true,
    guildIdOverride,
  }: UserSearchOptions = {}
) => {
  const activeGuildId = useActiveGuildId();
  const guildId = guildIdOverride ?? activeGuildId;
  return useSearchInitiativeMembersApiV1CGuildIdInitiativesInitiativeIdMembersSearchGet(
    guildId,
    initiativeId as number,
    {
      ...memberSearchParams(search, userIds),
      page_size: pageSize,
    },
    {
      query: {
        enabled: enabled && guildId != null && initiativeId != null,
        staleTime: 30_000,
        placeholderData: keepPreviousData,
      },
    }
  );
};

/**
 * Which roster a member picker searches.
 * - `guild`: every guild member.
 * - `initiative`: one initiative's members (mentions, linked members).
 * - `canOpen`: the people who can open one row, who are the ones that may be
 *   named on what it holds (task assignees, event attendees, person
 *   properties, queue items).
 */
export type MemberSearchScope =
  | { type: "guild"; guildIdOverride?: number }
  | { type: "initiative"; initiativeId: number | null | undefined }
  | { type: "canOpen"; tool: Tool; id: number | null | undefined };

/**
 * One entry point for the member typeaheads, selected by `scope`. Both
 * underlying queries are declared (rules of hooks) but only the scope-matching
 * one is enabled, so exactly one request fires.
 */
export const useMemberSearch = (
  scope: MemberSearchScope,
  {
    search,
    userIds,
    pageSize = USER_SEARCH_PAGE_SIZE,
    enabled = true,
  }: Omit<UserSearchOptions, "guildIdOverride" | "canOpen"> = {}
) => {
  const guildQuery = useUserSearch({
    search,
    userIds,
    pageSize,
    enabled: enabled && scope.type !== "initiative",
    guildIdOverride: scope.type === "guild" ? scope.guildIdOverride : undefined,
    canOpen: scope.type === "canOpen" ? { tool: scope.tool, id: scope.id } : undefined,
  });
  const initiativeQuery = useInitiativeMemberSearch(
    scope.type === "initiative" ? scope.initiativeId : undefined,
    { search, userIds, pageSize, enabled: enabled && scope.type === "initiative" }
  );

  return scope.type === "initiative" ? initiativeQuery : guildQuery;
};

export type { UserSummary };

// ── Mutations ───────────────────────────────────────────────────────────────

type UpdateCurrentUserVars = Parameters<typeof updateUsersMeApiV1UsersMePatch>[0];

export const useUpdateCurrentUser = (options?: MutationOpts<UserRead, UpdateCurrentUserVars>) =>
  useApiMutation<UserRead, UpdateCurrentUserVars>(
    {
      mutationFn: (data) => updateUsersMeApiV1UsersMePatch(data),
      invalidate: () => invalidate(q.currentUser()),
    },
    options
  );

export const useDeleteOwnAccount = (
  options?: MutationOpts<AccountDeletionResponse, AccountDeletionRequest>
) =>
  useApiMutation<AccountDeletionResponse, AccountDeletionRequest>(
    {
      mutationFn: (data) => deleteOwnAccountApiV1UsersMeDeleteAccountPost(data),
    },
    options
  );

export const useApproveUser = (options?: MutationOpts<UserGuildRead, number>) =>
  useGuildMutation<UserGuildRead, number>(
    {
      mutationFn: (guildId, userId) =>
        approveUserApiV1CGuildIdUsersUserIdApprovePost(guildId, userId),
      invalidate: () => invalidate(q.guildMembers()),
    },
    options
  );

type UpdateGuildMembershipVars = { guildId: number; userId: number; role: GuildRole };

export const useUpdateGuildMembership = (options?: MutationOpts<void, UpdateGuildMembershipVars>) =>
  useApiMutation<void, UpdateGuildMembershipVars>(
    {
      mutationFn: (data) =>
        updateGuildMembershipApiV1CommunitiesGuildIdMembersUserIdPatch(data.guildId, data.userId, {
          role: data.role,
        } as Parameters<typeof updateGuildMembershipApiV1CommunitiesGuildIdMembersUserIdPatch>[2]),
      invalidate: () => invalidate(q.guildMembers()),
    },
    options
  );

type ExportGuildUsersVars = {
  params: ExportUsersCsvApiV1CGuildIdUsersExportCsvGetParams;
  filename: string;
};

/** Download the guild members CSV from the backend and trigger a browser save. */
export const useExportGuildUsersCsv = (options?: MutationOpts<void, ExportGuildUsersVars>) =>
  useGuildMutation<void, ExportGuildUsersVars>(
    {
      mutationFn: async (guildId, { params, filename }) => {
        const blob = (await exportUsersCsvApiV1CGuildIdUsersExportCsvGet(guildId, params, {
          responseType: "blob",
          // FastAPI expects ?user_id=1&user_id=2; axios's default `[]` suffix gets ignored.
          paramsSerializer: { indexes: null },
        })) as Blob;
        downloadBlob(blob, filename);
      },
    },
    options
  );

export const useUpdateNotificationPreferences = (
  options?: MutationOpts<void, Record<string, boolean | string | number | null>>
) =>
  useApiMutation<void, Record<string, boolean | string | number | null>>(
    {
      mutationFn: async (data) => {
        await updateUsersMeApiV1UsersMePatch(
          data as Parameters<typeof updateUsersMeApiV1UsersMePatch>[0]
        );
      },
      invalidate: () => invalidate(q.currentUser()),
    },
    options
  );
