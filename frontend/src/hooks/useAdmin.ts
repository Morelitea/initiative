import { useMutation, useQuery } from "@tanstack/react-query";

import {
  listAllUsersApiV1AdminUsersGet,
  getListAllUsersApiV1AdminUsersGetQueryKey,
  getPlatformAdminCountApiV1AdminPlatformAdminCountGet,
  getGetPlatformAdminCountApiV1AdminPlatformAdminCountGetQueryKey,
  checkUserDeletionEligibilityApiV1AdminUsersUserIdDeletionEligibilityGet,
  getCheckUserDeletionEligibilityApiV1AdminUsersUserIdDeletionEligibilityGetQueryKey,
  deleteUserApiV1AdminUsersUserIdDelete,
  adminDeleteGuildApiV1AdminGuildsGuildIdDelete,
  adminDeleteInitiativeApiV1AdminInitiativesInitiativeIdDelete,
  adminUpdateGuildMemberRoleApiV1AdminGuildsGuildIdMembersUserIdRolePatch,
  adminUpdateInitiativeMemberRoleApiV1AdminInitiativesInitiativeIdMembersUserIdRolePatch,
  triggerPasswordResetApiV1AdminUsersUserIdResetPasswordPost,
  reactivateUserApiV1AdminUsersUserIdReactivatePost,
  updatePlatformRoleApiV1AdminUsersUserIdPlatformRolePatch,
  exportPlatformUsersCsvApiV1AdminUsersExportCsvGet,
} from "@/api/generated/admin/admin";
import {
  checkDeletionEligibilityApiV1UsersMeDeletionEligibilityGet,
  getCheckDeletionEligibilityApiV1UsersMeDeletionEligibilityGetQueryKey,
} from "@/api/generated/users/users";
import type {
  PlatformAdminCountResponse,
  AdminDeletionEligibilityResponse,
  DeletionEligibilityResponse,
  UserRead,
  AccountDeletionResponse,
  AdminUserDeleteRequest,
  UserRole,
  VerificationSendResponse,
  ExportPlatformUsersCsvApiV1AdminUsersExportCsvGetParams,
} from "@/api/generated/initiativeAPI.schemas";
import type { MutationOpts } from "@/types/mutation";
import type { QueryOpts } from "@/types/query";
import { invalidateAdminUsers, invalidateAllGuilds } from "@/api/query-keys";
import { downloadBlob } from "@/lib/csv";

// ── Queries ─────────────────────────────────────────────────────────────────

/** Fetch all platform users (admin only). */
export const usePlatformUsers = (options?: QueryOpts<UserRead[]>) => {
  return useQuery<UserRead[]>({
    queryKey: getListAllUsersApiV1AdminUsersGetQueryKey(),
    queryFn: () => listAllUsersApiV1AdminUsersGet() as unknown as Promise<UserRead[]>,
    ...options,
  });
};

/** Fetch the current count of platform admins (admin only). */
export const usePlatformAdminCount = (options?: QueryOpts<PlatformAdminCountResponse>) => {
  return useQuery<PlatformAdminCountResponse>({
    queryKey: getGetPlatformAdminCountApiV1AdminPlatformAdminCountGetQueryKey(),
    queryFn: () =>
      getPlatformAdminCountApiV1AdminPlatformAdminCountGet() as unknown as Promise<PlatformAdminCountResponse>,
    ...options,
  });
};

/**
 * Check whether a specific user can be deleted (admin only).
 *
 * Disabled by default -- call `refetch()` to trigger the eligibility check
 * on demand.
 */
export const useUserDeletionEligibility = (userId: number) => {
  return useQuery<AdminDeletionEligibilityResponse>({
    queryKey:
      getCheckUserDeletionEligibilityApiV1AdminUsersUserIdDeletionEligibilityGetQueryKey(userId),
    queryFn: () =>
      checkUserDeletionEligibilityApiV1AdminUsersUserIdDeletionEligibilityGet(
        userId
      ) as unknown as Promise<AdminDeletionEligibilityResponse>,
    enabled: false,
  });
};

/**
 * Check whether the current (logged-in) user can delete their own account.
 *
 * Disabled by default -- call `refetch()` to trigger the eligibility check
 * on demand.
 */
export const useMyDeletionEligibility = () => {
  return useQuery<DeletionEligibilityResponse>({
    queryKey: getCheckDeletionEligibilityApiV1UsersMeDeletionEligibilityGetQueryKey(),
    queryFn: () =>
      checkDeletionEligibilityApiV1UsersMeDeletionEligibilityGet() as unknown as Promise<DeletionEligibilityResponse>,
    enabled: false,
  });
};

// ── Mutations ─────────────────────────────────────────────────────────────────

/** Delete a user account (admin only). Closes over the target userId. */
export const useAdminDeleteUser = (
  userId: number,
  options?: MutationOpts<AccountDeletionResponse, AdminUserDeleteRequest>
) => {
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async (request: AdminUserDeleteRequest) => {
      return deleteUserApiV1AdminUsersUserIdDelete(
        userId,
        request
      ) as unknown as Promise<AccountDeletionResponse>;
    },
    onSuccess: (...args) => {
      void invalidateAdminUsers();
      onSuccess?.(...args);
    },
    onError: (...args) => {
      onError?.(...args);
    },
    onSettled,
  });
};

/** Promote a guild member to admin (admin only). */
export const useAdminPromoteGuildMember = (
  options?: MutationOpts<void, { guildId: number; userId: number }>
) => {
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async ({ guildId, userId }: { guildId: number; userId: number }) => {
      await adminUpdateGuildMemberRoleApiV1AdminGuildsGuildIdMembersUserIdRolePatch(
        guildId,
        userId,
        { role: "admin" }
      );
    },
    onSuccess: (...args) => {
      void invalidateAdminUsers();
      onSuccess?.(...args);
    },
    onError: (...args) => {
      onError?.(...args);
    },
    onSettled,
  });
};

/** Delete a guild (admin only). */
export const useAdminDeleteGuild = (options?: MutationOpts<void, number>) => {
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async (guildId: number) => {
      await adminDeleteGuildApiV1AdminGuildsGuildIdDelete(guildId);
    },
    onSuccess: (...args) => {
      void invalidateAdminUsers();
      void invalidateAllGuilds();
      onSuccess?.(...args);
    },
    onError: (...args) => {
      onError?.(...args);
    },
    onSettled,
  });
};

/** Delete an initiative (platform admin only).
 *
 * Used in the user-deletion blocker-resolution flow when the target
 * user is the sole project manager of an initiative with no other
 * members the admin can promote in their place.
 */
export const useAdminDeleteInitiative = (options?: MutationOpts<void, number>) => {
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async (initiativeId: number) => {
      await adminDeleteInitiativeApiV1AdminInitiativesInitiativeIdDelete(initiativeId);
    },
    onSuccess: (...args) => {
      void invalidateAdminUsers();
      onSuccess?.(...args);
    },
    onError: (...args) => {
      onError?.(...args);
    },
    onSettled,
  });
};

/** Promote an initiative member to project manager (admin only). */
export const useAdminPromoteInitiativeMember = (
  options?: MutationOpts<void, { initiativeId: number; userId: number }>
) => {
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async ({ initiativeId, userId }: { initiativeId: number; userId: number }) => {
      await adminUpdateInitiativeMemberRoleApiV1AdminInitiativesInitiativeIdMembersUserIdRolePatch(
        initiativeId,
        userId,
        { role: "project_manager" }
      );
    },
    onSuccess: (...args) => {
      void invalidateAdminUsers();
      onSuccess?.(...args);
    },
    onError: (...args) => {
      onError?.(...args);
    },
    onSettled,
  });
};

/** Trigger a password reset email for a user (admin only). */
export const useAdminTriggerPasswordReset = (
  options?: MutationOpts<VerificationSendResponse, number>
) => {
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async (userId: number) => {
      return triggerPasswordResetApiV1AdminUsersUserIdResetPasswordPost(
        userId
      ) as unknown as Promise<VerificationSendResponse>;
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

/** Reactivate a deactivated user (admin only). */
export const useAdminReactivateUser = (options?: MutationOpts<UserRead, number>) => {
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async (userId: number) => {
      return reactivateUserApiV1AdminUsersUserIdReactivatePost(
        userId
      ) as unknown as Promise<UserRead>;
    },
    onSuccess: (...args) => {
      void invalidateAdminUsers();
      onSuccess?.(...args);
    },
    onError: (...args) => {
      onError?.(...args);
    },
    onSettled,
  });
};

type ExportPlatformUsersVars = {
  params: ExportPlatformUsersCsvApiV1AdminUsersExportCsvGetParams;
  filename: string;
};

/** Download the platform users CSV from the backend and trigger a browser save. */
export const useExportPlatformUsersCsv = (
  options?: MutationOpts<void, ExportPlatformUsersVars>
) => {
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async ({ params, filename }: ExportPlatformUsersVars) => {
      const blob = (await exportPlatformUsersCsvApiV1AdminUsersExportCsvGet(params, {
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

/** Update a user's platform role (admin only). */
export const useAdminUpdatePlatformRole = (
  options?: MutationOpts<UserRead, { userId: number; role: UserRole }>
) => {
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async ({ userId, role }: { userId: number; role: UserRole }) => {
      return updatePlatformRoleApiV1AdminUsersUserIdPlatformRolePatch(userId, {
        role,
      } as Parameters<
        typeof updatePlatformRoleApiV1AdminUsersUserIdPlatformRolePatch
      >[1]) as unknown as Promise<UserRead>;
    },
    onSuccess: (...args) => {
      void invalidateAdminUsers();
      onSuccess?.(...args);
    },
    onError: (...args) => {
      onError?.(...args);
    },
    onSettled,
  });
};
