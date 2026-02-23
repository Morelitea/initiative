import { useMutation, useQuery } from "@tanstack/react-query";

import {
  listUsersApiV1UsersGet,
  getListUsersApiV1UsersGetQueryKey,
  updateUsersMeApiV1UsersMePatch,
  deleteOwnAccountApiV1UsersMeDeleteAccountPost,
  approveUserApiV1UsersUserIdApprovePost,
  deleteUserApiV1UsersUserIdDelete,
} from "@/api/generated/users/users";
import { updateGuildMembershipApiV1GuildsGuildIdMembersUserIdPatch } from "@/api/generated/guilds/guilds";
import { invalidateUsersList, invalidateCurrentUser } from "@/api/query-keys";
import type { MutationOpts } from "@/types/mutation";
import type { QueryOpts } from "@/types/query";
import type {
  UserGuildMember,
  GuildRole,
  UserRead,
  AccountDeletionRequest,
  AccountDeletionResponse,
} from "@/api/generated/initiativeAPI.schemas";

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

export const useRemoveGuildMember = (options?: MutationOpts<void, number>) => {
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async (userId: number) => {
      await deleteUserApiV1UsersUserIdDelete(userId);
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

export const useUpdateNotificationPreferences = (
  options?: MutationOpts<void, Record<string, boolean | string>>
) => {
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async (data: Record<string, boolean | string>) => {
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
