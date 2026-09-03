import { useQuery } from "@tanstack/react-query";

import {
  adminDeleteGuildApiV1AdminGuildsGuildIdDelete,
  adminDeleteInitiativeApiV1AdminInitiativesInitiativeIdDelete,
  adminUpdateGuildMemberRoleApiV1AdminGuildsGuildIdMembersUserIdRolePatch,
  adminUpdateInitiativeMemberRoleApiV1AdminInitiativesInitiativeIdMembersUserIdRolePatch,
  checkUserDeletionEligibilityApiV1AdminUsersUserIdDeletionEligibilityGet,
  clearAgeBlockApiV1AdminUsersUserIdAgeBlockDelete,
  deleteUserApiV1AdminUsersUserIdDelete,
  exportPlatformUsersCsvApiV1AdminUsersExportCsvGet,
  getCheckUserDeletionEligibilityApiV1AdminUsersUserIdDeletionEligibilityGetQueryKey,
  getGetPlatformAdminCountApiV1AdminPlatformAdminCountGetQueryKey,
  getListAllUsersApiV1AdminUsersGetQueryKey,
  getListAuditEventsApiV1AdminAuditEventsGetQueryKey,
  getPlatformAdminCountApiV1AdminPlatformAdminCountGet,
  listAllUsersApiV1AdminUsersGet,
  listAuditEventsApiV1AdminAuditEventsGet,
  reactivateUserApiV1AdminUsersUserIdReactivatePost,
  setUserSuspensionApiV1AdminUsersUserIdSuspensionPost,
  setUserUsernameApiV1AdminUsersUserIdUsernamePatch,
  triggerPasswordResetApiV1AdminUsersUserIdResetPasswordPost,
  updatePlatformRoleApiV1AdminUsersUserIdPlatformRolePatch,
} from "@/api/generated/admin/admin";
import type {
  AccountDeletionResponse,
  AdminDeletionEligibilityResponse,
  AdminUserDeleteRequest,
  AuditEventListResponse,
  DeletionEligibilityResponse,
  ExportPlatformUsersCsvApiV1AdminUsersExportCsvGetParams,
  ListAuditEventsApiV1AdminAuditEventsGetParams,
  PlatformAdminCountResponse,
  UserRead,
  UserRole,
  VerificationSendResponse,
} from "@/api/generated/initiativeAPI.schemas";
import {
  checkDeletionEligibilityApiV1UsersMeDeletionEligibilityGet,
  getCheckDeletionEligibilityApiV1UsersMeDeletionEligibilityGetQueryKey,
} from "@/api/generated/users/users";
import { invalidateAdminUsers, invalidateAllGuilds } from "@/api/query-keys";
import { useApiMutation } from "@/hooks/useApiMutation";
import { downloadBlob } from "@/lib/csv";
import type { MutationOpts } from "@/types/mutation";
import type { QueryOpts } from "@/types/query";

// ── Queries ─────────────────────────────────────────────────────────────────

/** Fetch all platform users (admin only). */
export const usePlatformUsers = (options?: QueryOpts<UserRead[]>) => {
  return useQuery<UserRead[]>({
    queryKey: getListAllUsersApiV1AdminUsersGetQueryKey(),
    queryFn: () => listAllUsersApiV1AdminUsersGet(),
    ...options,
  });
};

/** One page of the audit board (``audit.read`` — support and above). */
export const usePlatformAuditEvents = (
  params: ListAuditEventsApiV1AdminAuditEventsGetParams,
  options?: QueryOpts<AuditEventListResponse>
) => {
  return useQuery<AuditEventListResponse>({
    queryKey: getListAuditEventsApiV1AdminAuditEventsGetQueryKey(params),
    queryFn: () => listAuditEventsApiV1AdminAuditEventsGet(params),
    ...options,
  });
};

/** Fetch the current count of platform admins (admin only). */
export const usePlatformAdminCount = (options?: QueryOpts<PlatformAdminCountResponse>) => {
  return useQuery<PlatformAdminCountResponse>({
    queryKey: getGetPlatformAdminCountApiV1AdminPlatformAdminCountGetQueryKey(),
    queryFn: () => getPlatformAdminCountApiV1AdminPlatformAdminCountGet(),
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
    queryFn: () => checkUserDeletionEligibilityApiV1AdminUsersUserIdDeletionEligibilityGet(userId),
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
    queryFn: () => checkDeletionEligibilityApiV1UsersMeDeletionEligibilityGet(),
    enabled: false,
  });
};

// ── Mutations ─────────────────────────────────────────────────────────────────

/** Delete a user account (admin only). Closes over the target userId. */
export const useAdminDeleteUser = (
  userId: number,
  options?: MutationOpts<AccountDeletionResponse, AdminUserDeleteRequest>
) =>
  useApiMutation<AccountDeletionResponse, AdminUserDeleteRequest>(
    {
      mutationFn: (request) => deleteUserApiV1AdminUsersUserIdDelete(userId, request),
      invalidate: () => invalidateAdminUsers(),
    },
    options
  );

/** Promote a guild member to admin (admin only). */
export const useAdminPromoteGuildMember = (
  options?: MutationOpts<void, { guildId: number; userId: number }>
) =>
  useApiMutation<void, { guildId: number; userId: number }>(
    {
      mutationFn: ({ guildId, userId }) =>
        adminUpdateGuildMemberRoleApiV1AdminGuildsGuildIdMembersUserIdRolePatch(guildId, userId, {
          role: "admin",
        }),
      invalidate: () => invalidateAdminUsers(),
    },
    options
  );

/** Delete a guild that blocks a user's deletion (operator blocker resolution).
 * The guild must be one `blockedUserId` is the sole admin of. */
export const useAdminDeleteGuild = (
  options?: MutationOpts<void, { guildId: number; blockedUserId: number }>
) =>
  useApiMutation<void, { guildId: number; blockedUserId: number }>(
    {
      mutationFn: ({ guildId, blockedUserId }) =>
        adminDeleteGuildApiV1AdminGuildsGuildIdDelete(guildId, {
          blocked_user_id: blockedUserId,
        }),
      invalidate: () => Promise.all([invalidateAdminUsers(), invalidateAllGuilds()]),
    },
    options
  );

/** Delete an initiative (platform admin only).
 *
 * Used in the user-deletion blocker-resolution flow when the target
 * user is the sole project manager of an initiative with no other
 * members the admin can promote in their place.
 */
export const useAdminDeleteInitiative = (
  options?: MutationOpts<void, { initiativeId: number; guildId: number }>
) =>
  useApiMutation<void, { initiativeId: number; guildId: number }>(
    {
      mutationFn: ({ initiativeId, guildId }) =>
        adminDeleteInitiativeApiV1AdminInitiativesInitiativeIdDelete(initiativeId, {
          guild_id: guildId,
        }),
      invalidate: () => invalidateAdminUsers(),
    },
    options
  );

/** Promote an initiative member to project manager (admin only). */
export const useAdminPromoteInitiativeMember = (
  options?: MutationOpts<void, { initiativeId: number; userId: number; guildId: number }>
) =>
  useApiMutation<void, { initiativeId: number; userId: number; guildId: number }>(
    {
      mutationFn: ({ initiativeId, userId, guildId }) =>
        adminUpdateInitiativeMemberRoleApiV1AdminInitiativesInitiativeIdMembersUserIdRolePatch(
          initiativeId,
          userId,
          { role: "project_manager" },
          { guild_id: guildId }
        ),
      invalidate: () => invalidateAdminUsers(),
    },
    options
  );

/** Trigger a password reset email for a user (admin only). */
export const useAdminTriggerPasswordReset = (
  options?: MutationOpts<VerificationSendResponse, number>
) =>
  useApiMutation<VerificationSendResponse, number>(
    {
      mutationFn: (userId) => triggerPasswordResetApiV1AdminUsersUserIdResetPasswordPost(userId),
    },
    options
  );

/** Reactivate a deactivated user (admin only). */
export const useAdminReactivateUser = (options?: MutationOpts<UserRead, number>) =>
  useApiMutation<UserRead, number>(
    {
      mutationFn: (userId) => reactivateUserApiV1AdminUsersUserIdReactivatePost(userId),
      invalidate: () => invalidateAdminUsers(),
    },
    options
  );

type SetUsernameVars = { userId: number; username: string };

/** Change someone's username (``content.moderate``). The number is not the
 *  moderator's to choose; the server keeps the one they have. */
export const useAdminSetUsername = (options?: MutationOpts<UserRead, SetUsernameVars>) =>
  useApiMutation<UserRead, SetUsernameVars>(
    {
      mutationFn: ({ userId, username }) =>
        setUserUsernameApiV1AdminUsersUserIdUsernamePatch(userId, { username }),
      invalidate: () => invalidateAdminUsers(),
    },
    options
  );

type SetSuspensionVars = { userId: number; suspended: boolean; reason?: string };

/** Freeze an account, or let it go (``users.manage``). Takes nothing away —
 *  memberships, grants and content are all still there when it is lifted. */
export const useAdminSetSuspension = (options?: MutationOpts<UserRead, SetSuspensionVars>) =>
  useApiMutation<UserRead, SetSuspensionVars>(
    {
      mutationFn: ({ userId, suspended, reason }) =>
        setUserSuspensionApiV1AdminUsersUserIdSuspensionPost(userId, {
          suspended,
          reason: reason || null,
        }),
      invalidate: () => invalidateAdminUsers(),
    },
    options
  );

/** Let an account answer the age question again (``users.age_unblock``).
 *  For the case that is nearly all of them: a mistyped year. It clears the
 *  record that the question was answered and nothing else — the date was never
 *  kept, so there is nothing else to clear. */
export const useAdminClearAgeBlock = (options?: MutationOpts<UserRead, number>) =>
  useApiMutation<UserRead, number>(
    {
      mutationFn: (userId) => clearAgeBlockApiV1AdminUsersUserIdAgeBlockDelete(userId),
      invalidate: () => invalidateAdminUsers(),
    },
    options
  );

type ExportPlatformUsersVars = {
  params: ExportPlatformUsersCsvApiV1AdminUsersExportCsvGetParams;
  filename: string;
};

/** Download the platform users CSV from the backend and trigger a browser save. */
export const useExportPlatformUsersCsv = (options?: MutationOpts<void, ExportPlatformUsersVars>) =>
  useApiMutation<void, ExportPlatformUsersVars>(
    {
      mutationFn: async ({ params, filename }) => {
        const blob = (await exportPlatformUsersCsvApiV1AdminUsersExportCsvGet(params, {
          responseType: "blob",
          // FastAPI expects ?user_id=1&user_id=2; axios's default `[]` suffix gets ignored.
          paramsSerializer: { indexes: null },
        })) as Blob;
        downloadBlob(blob, filename);
      },
    },
    options
  );

/** Update a user's platform role (admin only). */
export const useAdminUpdatePlatformRole = (
  options?: MutationOpts<UserRead, { userId: number; role: UserRole }>
) =>
  useApiMutation<UserRead, { userId: number; role: UserRole }>(
    {
      mutationFn: ({ userId, role }) =>
        updatePlatformRoleApiV1AdminUsersUserIdPlatformRolePatch(userId, {
          role,
        } as Parameters<typeof updatePlatformRoleApiV1AdminUsersUserIdPlatformRolePatch>[1]),
      invalidate: () => invalidateAdminUsers(),
    },
    options
  );
