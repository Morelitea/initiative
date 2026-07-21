import { keepPreviousData, useMutation, useQuery } from "@tanstack/react-query";

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
  useSearchUsersApiV1GGuildIdUsersSearchGet,
} from "@/api/generated/users/users";
import { invalidateCurrentUser, invalidateGuildMembers } from "@/api/query-keys";
import { useActiveGuildId } from "@/hooks/useActiveGuildId";
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
    queryFn: () => listUsersApiV1GGuildIdUsersGet(guildId) as unknown as Promise<UserGuildMember[]>,
    ...options,
  });
};

/** Default page size for slim member typeaheads — mirrors the CommandCenter
 *  task search (a bounded dropdown-sized window, not the whole roster). */
export const USER_SEARCH_PAGE_SIZE = 25;

export interface UserSearchOptions {
  /** Case-insensitive substring match on the member's name. */
  search?: string;
  /** Bounded page size (server caps at 100). */
  pageSize?: number;
  /** Gate the request — pass the picker's `open` state so we don't fetch until
   *  the dropdown is shown. */
  enabled?: boolean;
  /** Read a specific guild instead of the active one (cross-guild surfaces). */
  guildIdOverride?: number;
}

/**
 * Slim, server-side member typeahead for the active guild. Returns
 * {@link UserSummary} rows (id, name, avatar, status) for a bounded page —
 * the replacement for loading the whole roster via {@link useUsers} and
 * filtering client-side. Debounce the `search` value at the call site.
 */
export const useUserSearch = ({
  search,
  pageSize = USER_SEARCH_PAGE_SIZE,
  enabled = true,
  guildIdOverride,
}: UserSearchOptions = {}) => {
  const activeGuildId = useActiveGuildId();
  const guildId = guildIdOverride ?? activeGuildId;
  const trimmed = search?.trim();
  return useSearchUsersApiV1GGuildIdUsersSearchGet(
    guildId,
    { search: trimmed || undefined, page_size: pageSize },
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
    pageSize = USER_SEARCH_PAGE_SIZE,
    enabled = true,
    guildIdOverride,
  }: UserSearchOptions = {}
) => {
  const activeGuildId = useActiveGuildId();
  const guildId = guildIdOverride ?? activeGuildId;
  const trimmed = search?.trim();
  return useSearchInitiativeMembersApiV1GGuildIdInitiativesInitiativeIdMembersSearchGet(
    guildId,
    initiativeId as number,
    { search: trimmed || undefined, page_size: pageSize },
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
    pageSize = USER_SEARCH_PAGE_SIZE,
    enabled = true,
    guildIdOverride,
  }: UserSearchOptions = {}
) => {
  const activeGuildId = useActiveGuildId();
  const guildId = guildIdOverride ?? activeGuildId;
  const trimmed = search?.trim();
  return useSearchProjectMembersApiV1GGuildIdProjectsProjectIdMembersSearchGet(
    guildId,
    projectId as number,
    { search: trimmed || undefined, page_size: pageSize },
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
    pageSize = USER_SEARCH_PAGE_SIZE,
    enabled = true,
  }: Omit<UserSearchOptions, "guildIdOverride"> = {}
) => {
  const guildQuery = useUserSearch({
    search,
    pageSize,
    enabled: enabled && scope.type === "guild",
    guildIdOverride: scope.type === "guild" ? scope.guildIdOverride : undefined,
  });
  const initiativeQuery = useInitiativeMemberSearch(
    scope.type === "initiative" ? scope.initiativeId : undefined,
    { search, pageSize, enabled: enabled && scope.type === "initiative" }
  );
  const projectQuery = useProjectMemberSearch(
    scope.type === "project" ? scope.projectId : undefined,
    { search, pageSize, enabled: enabled && scope.type === "project" }
  );

  if (scope.type === "guild") return guildQuery;
  if (scope.type === "initiative") return initiativeQuery;
  return projectQuery;
};

export type { UserSummary };

// ── Mutations ───────────────────────────────────────────────────────────────

type UpdateCurrentUserVars = Parameters<typeof updateUsersMeApiV1UsersMePatch>[0];

export const useUpdateCurrentUser = (options?: MutationOpts<UserRead, UpdateCurrentUserVars>) => {
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async (data: UpdateCurrentUserVars) => {
      return updateUsersMeApiV1UsersMePatch(data) as unknown as Promise<UserRead>;
    },
    onSuccess: (...args) => {
      void invalidateCurrentUser();
      onSuccess?.(...args);
    },
    onError: (...args) => {
      onError?.(...args);
    },
    onSettled,
  });
};

export const useDeleteOwnAccount = (
  options?: MutationOpts<AccountDeletionResponse, AccountDeletionRequest>
) => {
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async (data: AccountDeletionRequest) => {
      return deleteOwnAccountApiV1UsersMeDeleteAccountPost(
        data
      ) as unknown as Promise<AccountDeletionResponse>;
    },
    onSuccess: (...args) => {
      onSuccess?.(...args);
    },
    onError: (...args) => {
      onError?.(...args);
    },
    onSettled,
  });
};

export const useApproveUser = (options?: MutationOpts<UserRead, number>) => {
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};
  const guildId = useActiveGuildId();

  return useMutation({
    ...rest,
    mutationFn: async (userId: number) => {
      return approveUserApiV1GGuildIdUsersUserIdApprovePost(
        guildId,
        userId
      ) as unknown as Promise<UserRead>;
    },
    onSuccess: (...args) => {
      void invalidateGuildMembers();
      onSuccess?.(...args);
    },
    onError: (...args) => {
      onError?.(...args);
    },
    onSettled,
  });
};

type UpdateGuildMembershipVars = { guildId: number; userId: number; role: GuildRole };

export const useUpdateGuildMembership = (
  options?: MutationOpts<void, UpdateGuildMembershipVars>
) => {
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async (data: UpdateGuildMembershipVars) => {
      await updateGuildMembershipApiV1GuildsGuildIdMembersUserIdPatch(data.guildId, data.userId, {
        role: data.role,
      } as Parameters<typeof updateGuildMembershipApiV1GuildsGuildIdMembersUserIdPatch>[2]);
    },
    onSuccess: (...args) => {
      void invalidateGuildMembers();
      onSuccess?.(...args);
    },
    onError: (...args) => {
      onError?.(...args);
    },
    onSettled,
  });
};

type ExportGuildUsersVars = {
  params: ExportUsersCsvApiV1GGuildIdUsersExportCsvGetParams;
  filename: string;
};

/** Download the guild members CSV from the backend and trigger a browser save. */
export const useExportGuildUsersCsv = (options?: MutationOpts<void, ExportGuildUsersVars>) => {
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};
  const guildId = useActiveGuildId();

  return useMutation({
    ...rest,
    mutationFn: async ({ params, filename }: ExportGuildUsersVars) => {
      const blob = (await exportUsersCsvApiV1GGuildIdUsersExportCsvGet(guildId, params, {
        responseType: "blob",
        // FastAPI expects ?user_id=1&user_id=2; axios's default `[]` suffix gets ignored.
        paramsSerializer: { indexes: null },
      })) as Blob;
      downloadBlob(blob, filename);
    },
    onSuccess: (...args) => {
      onSuccess?.(...args);
    },
    onError: (...args) => {
      onError?.(...args);
    },
    onSettled,
  });
};

export const useUpdateNotificationPreferences = (
  options?: MutationOpts<void, Record<string, boolean | string | number | null>>
) => {
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async (data: Record<string, boolean | string | number | null>) => {
      await updateUsersMeApiV1UsersMePatch(
        data as Parameters<typeof updateUsersMeApiV1UsersMePatch>[0]
      );
    },
    onSuccess: (...args) => {
      void invalidateCurrentUser();
      onSuccess?.(...args);
    },
    onError: (...args) => {
      onError?.(...args);
    },
    onSettled,
  });
};
