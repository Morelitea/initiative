import { useMutation, useQuery } from "@tanstack/react-query";

import { updateGuildMembershipApiV1GuildsGuildIdMembersUserIdPatch } from "@/api/generated/guilds/guilds";
import type {
  AccountDeletionRequest,
  AccountDeletionResponse,
  ExportUsersCsvApiV1UsersExportCsvGetParams,
  GuildRole,
  UserGuildMember,
  UserRead,
} from "@/api/generated/initiativeAPI.schemas";
import {
  approveUserApiV1UsersUserIdApprovePost,
  deleteOwnAccountApiV1UsersMeDeleteAccountPost,
  exportUsersCsvApiV1UsersExportCsvGet,
  getListUsersApiV1UsersGetQueryKey,
  listUsersApiV1UsersGet,
  updateUsersMeApiV1UsersMePatch,
} from "@/api/generated/users/users";
import { invalidateCurrentUser, invalidateUsersList } from "@/api/query-keys";
import { downloadBlob } from "@/lib/csv";
import type { MutationOpts } from "@/types/mutation";
import type { QueryOpts } from "@/types/query";

// ── Queries ─────────────────────────────────────────────────────────────────

export const useUsers = (options?: QueryOpts<UserGuildMember[]>) => {
  return useQuery<UserGuildMember[]>({
    queryKey: getListUsersApiV1UsersGetQueryKey(),
    queryFn: () => listUsersApiV1UsersGet() as unknown as Promise<UserGuildMember[]>,
    ...options,
  });
};

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

  return useMutation({
    ...rest,
    mutationFn: async (userId: number) => {
      return approveUserApiV1UsersUserIdApprovePost(userId) as unknown as Promise<UserRead>;
    },
    onSuccess: (...args) => {
      void invalidateUsersList();
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
      void invalidateUsersList();
      onSuccess?.(...args);
    },
    onError: (...args) => {
      onError?.(...args);
    },
    onSettled,
  });
};

type ExportGuildUsersVars = {
  params: ExportUsersCsvApiV1UsersExportCsvGetParams;
  filename: string;
};

/** Download the guild members CSV from the backend and trigger a browser save. */
export const useExportGuildUsersCsv = (options?: MutationOpts<void, ExportGuildUsersVars>) => {
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async ({ params, filename }: ExportGuildUsersVars) => {
      const blob = (await exportUsersCsvApiV1UsersExportCsvGet(params, {
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
