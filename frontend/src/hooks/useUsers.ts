import { keepPreviousData, useQuery } from "@tanstack/react-query";

import { updateGuildMembershipApiV1GuildsGuildIdMembersUserIdPatch } from "@/api/generated/guilds/guilds";
import type {
  AccountDeletionRequest,
  AccountDeletionResponse,
  ExportUsersCsvApiV1GGuildIdUsersExportCsvGetParams,
  GuildRole,
  UserGuildMember,
  UserRead,
  UserSummary,
} from "@/api/generated/initiativeAPI.schemas";
import { useSearchInitiativeMembersApiV1GGuildIdInitiativesInitiativeIdMembersSearchGet } from "@/api/generated/initiatives/initiatives";
import { useSearchProjectMembersApiV1GGuildIdProjectsProjectIdMembersSearchGet } from "@/api/generated/projects/projects";
import {
  approveUserApiV1GGuildIdUsersUserIdApprovePost,
  deleteOwnAccountApiV1UsersMeDeleteAccountPost,
  exportUsersCsvApiV1GGuildIdUsersExportCsvGet,
  getListUsersApiV1GGuildIdUsersGetQueryKey,
  listUsersApiV1GGuildIdUsersGet,
  updateUsersMeApiV1UsersMePatch,
  useListMyDecorationsApiV1UsersMeDecorationsGet,
  useReadUserProfileApiV1UsersUserIdProfileGet,
  useSearchUsersApiV1GGuildIdUsersSearchGet,
} from "@/api/generated/users/users";
import { invalidateCurrentUser, invalidateGuildMembers } from "@/api/query-keys";
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
    queryKey: getListUsersApiV1GGuildIdUsersGetQueryKey(guildId),
    queryFn: () => listUsersApiV1GGuildIdUsersGet(guildId),
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
 * One person's profile.
 *
 * Public and community-independent: the same page whoever opens it, so there
 * is no guild in the call.
 */
export const useUserProfile = (userId: number | null | undefined) =>
  useReadUserProfileApiV1UsersUserIdProfileGet(userId as number, {
    query: {
      enabled: userId != null,
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
}: UserSearchOptions = {}) => {
  const activeGuildId = useActiveGuildId();
  const guildId = guildIdOverride ?? activeGuildId;
  return useSearchUsersApiV1GGuildIdUsersSearchGet(
    guildId,
    {
      ...memberSearchParams(search, userIds),
      page_size: pageSize,
      ...(page != null ? { page } : {}),
    },
    {
      query: {
        enabled: enabled && guildId != null,
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
  return useSearchInitiativeMembersApiV1GGuildIdInitiativesInitiativeIdMembersSearchGet(
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
 * Slim, server-side typeahead over the users **assignable to a project's
 * tasks** — the project's write/owner DAC set, computed server-side. Replaces
 * the client-side `project.grants` filtering the assignee pickers used to run
 * over the full guild roster.
 */
export const useProjectMemberSearch = (
  projectId: number | null | undefined,
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
  return useSearchProjectMembersApiV1GGuildIdProjectsProjectIdMembersSearchGet(
    guildId,
    projectId as number,
    {
      ...memberSearchParams(search, userIds),
      page_size: pageSize,
    },
    {
      query: {
        enabled: enabled && guildId != null && projectId != null,
        staleTime: 30_000,
        placeholderData: keepPreviousData,
      },
    }
  );
};

/**
 * Which RLS-scoped roster a member picker searches.
 * - `guild`: every guild member (e.g. a user-reference property).
 * - `initiative`: one initiative's members (linked-member / event pickers).
 * - `project`: users assignable to a project's tasks (write/owner DAC set).
 */
export type MemberSearchScope =
  | { type: "guild"; guildIdOverride?: number }
  | { type: "initiative"; initiativeId: number | null | undefined }
  | { type: "project"; projectId: number | null | undefined };

/**
 * One entry point for the three slim member typeaheads, selected by `scope`.
 * All three underlying queries are declared (rules of hooks) but only the
 * scope-matching one is enabled, so exactly one request fires. Returns the
 * active query result (`{ data, isLoading, ... }`).
 */
export const useMemberSearch = (
  scope: MemberSearchScope,
  {
    search,
    userIds,
    pageSize = USER_SEARCH_PAGE_SIZE,
    enabled = true,
  }: Omit<UserSearchOptions, "guildIdOverride"> = {}
) => {
  const guildQuery = useUserSearch({
    search,
    userIds,
    pageSize,
    enabled: enabled && scope.type === "guild",
    guildIdOverride: scope.type === "guild" ? scope.guildIdOverride : undefined,
  });
  const initiativeQuery = useInitiativeMemberSearch(
    scope.type === "initiative" ? scope.initiativeId : undefined,
    { search, userIds, pageSize, enabled: enabled && scope.type === "initiative" }
  );
  const projectQuery = useProjectMemberSearch(
    scope.type === "project" ? scope.projectId : undefined,
    { search, userIds, pageSize, enabled: enabled && scope.type === "project" }
  );

  if (scope.type === "guild") return guildQuery;
  if (scope.type === "initiative") return initiativeQuery;
  return projectQuery;
};

export type { UserSummary };

// ── Mutations ───────────────────────────────────────────────────────────────

type UpdateCurrentUserVars = Parameters<typeof updateUsersMeApiV1UsersMePatch>[0];

export const useUpdateCurrentUser = (options?: MutationOpts<UserRead, UpdateCurrentUserVars>) =>
  useApiMutation<UserRead, UpdateCurrentUserVars>(
    {
      mutationFn: (data) => updateUsersMeApiV1UsersMePatch(data),
      invalidate: () => invalidateCurrentUser(),
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

export const useApproveUser = (options?: MutationOpts<UserRead, number>) =>
  useGuildMutation<UserRead, number>(
    {
      mutationFn: (guildId, userId) =>
        approveUserApiV1GGuildIdUsersUserIdApprovePost(guildId, userId),
      invalidate: () => invalidateGuildMembers(),
    },
    options
  );

type UpdateGuildMembershipVars = { guildId: number; userId: number; role: GuildRole };

export const useUpdateGuildMembership = (options?: MutationOpts<void, UpdateGuildMembershipVars>) =>
  useApiMutation<void, UpdateGuildMembershipVars>(
    {
      mutationFn: (data) =>
        updateGuildMembershipApiV1GuildsGuildIdMembersUserIdPatch(data.guildId, data.userId, {
          role: data.role,
        } as Parameters<typeof updateGuildMembershipApiV1GuildsGuildIdMembersUserIdPatch>[2]),
      invalidate: () => invalidateGuildMembers(),
    },
    options
  );

type ExportGuildUsersVars = {
  params: ExportUsersCsvApiV1GGuildIdUsersExportCsvGetParams;
  filename: string;
};

/** Download the guild members CSV from the backend and trigger a browser save. */
export const useExportGuildUsersCsv = (options?: MutationOpts<void, ExportGuildUsersVars>) =>
  useGuildMutation<void, ExportGuildUsersVars>(
    {
      mutationFn: async (guildId, { params, filename }) => {
        const blob = (await exportUsersCsvApiV1GGuildIdUsersExportCsvGet(guildId, params, {
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
      invalidate: () => invalidateCurrentUser(),
    },
    options
  );
