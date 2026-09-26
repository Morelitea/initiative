import { keepPreviousData, useQuery } from "@tanstack/react-query";

import type {
  AccountDeletionResponse,
  DeletionEligibilityResponse,
  ExportPlatformUsersCsvApiV1OperatorUsersExportCsvGetParams,
  ListAllUsersApiV1OperatorUsersGetParams,
  OperatorDeletionEligibilityResponse,
  OperatorUserDeleteRequest,
  OperatorUserListResponse,
  OperatorUserRead,
  UserRole,
  VerificationSendResponse,
} from "@/api/generated/initiativeAPI.schemas";
import {
  checkUserDeletionEligibilityApiV1OperatorUsersUserIdDeletionEligibilityGet,
  clearAgeBlockApiV1OperatorUsersUserIdAgeBlockDelete,
  deleteUserApiV1OperatorUsersUserIdDelete,
  exportPlatformUsersCsvApiV1OperatorUsersExportCsvGet,
  getCheckUserDeletionEligibilityApiV1OperatorUsersUserIdDeletionEligibilityGetQueryKey,
  getListAllUsersApiV1OperatorUsersGetQueryKey,
  liftSignInLockApiV1OperatorUsersUserIdSignInLockDelete,
  listAllUsersApiV1OperatorUsersGet,
  reactivateUserApiV1OperatorUsersUserIdReactivatePost,
  removeUserAvatarApiV1OperatorUsersUserIdAvatarDelete,
  restoreDeletedUserApiV1OperatorUsersUserIdRestorePost,
  setUserSuspensionApiV1OperatorUsersUserIdSuspensionPost,
  setUserUsernameApiV1OperatorUsersUserIdUsernamePatch,
  triggerPasswordResetApiV1OperatorUsersUserIdResetPasswordPost,
  updatePlatformRoleApiV1OperatorUsersUserIdPlatformRolePatch,
} from "@/api/generated/operator/operator";
import {
  checkDeletionEligibilityApiV1UsersMeDeletionEligibilityGet,
  getCheckDeletionEligibilityApiV1UsersMeDeletionEligibilityGetQueryKey,
} from "@/api/generated/users/users";
import { invalidate, q } from "@/api/query-keys";
import { useApiMutation } from "@/hooks/useApiMutation";
import { downloadBlob } from "@/lib/csv";
import type { MutationOpts } from "@/types/mutation";
import type { QueryOpts } from "@/types/query";

// ── Queries ─────────────────────────────────────────────────────────────────

/** One page of platform users (operator endpoint), searched and sorted on the
 *  server. The previous page stays on screen while the next one loads. */
export const usePlatformUsers = (
  params: ListAllUsersApiV1OperatorUsersGetParams,
  options?: QueryOpts<OperatorUserListResponse>
) => {
  return useQuery<OperatorUserListResponse>({
    queryKey: getListAllUsersApiV1OperatorUsersGetQueryKey(params),
    queryFn: () => listAllUsersApiV1OperatorUsersGet(params),
    placeholderData: keepPreviousData,
    ...options,
  });
};

/**
 * Check whether a specific user can be deleted (operator endpoint).
 *
 * Disabled by default -- call `refetch()` to trigger the eligibility check
 * on demand.
 */
export const useUserDeletionEligibility = (userId: number) => {
  return useQuery<OperatorDeletionEligibilityResponse>({
    queryKey:
      getCheckUserDeletionEligibilityApiV1OperatorUsersUserIdDeletionEligibilityGetQueryKey(userId),
    queryFn: () =>
      checkUserDeletionEligibilityApiV1OperatorUsersUserIdDeletionEligibilityGet(userId),
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

/** Delete a user account (operator endpoint). Closes over the target userId. */
export const useOperatorDeleteUser = (
  userId: number,
  options?: MutationOpts<AccountDeletionResponse, OperatorUserDeleteRequest>
) =>
  useApiMutation<AccountDeletionResponse, OperatorUserDeleteRequest>(
    {
      mutationFn: (request) => deleteUserApiV1OperatorUsersUserIdDelete(userId, request),
      invalidate: () => invalidate(q.operatorUsers()),
    },
    options
  );

/** Trigger a password reset email for a user (operator endpoint). */
export const useOperatorTriggerPasswordReset = (
  options?: MutationOpts<VerificationSendResponse, number>
) =>
  useApiMutation<VerificationSendResponse, number>(
    {
      mutationFn: (userId) => triggerPasswordResetApiV1OperatorUsersUserIdResetPasswordPost(userId),
    },
    options
  );

/** Reactivate a deactivated user (operator endpoint). */
export const useOperatorReactivateUser = (options?: MutationOpts<OperatorUserRead, number>) =>
  useApiMutation<OperatorUserRead, number>(
    {
      mutationFn: (userId) => reactivateUserApiV1OperatorUsersUserIdReactivatePost(userId),
      invalidate: () => invalidate(q.operatorUsers()),
    },
    options
  );

/** Call off a pending erasure (``users.manage``).
 *
 * Not the same thing as reactivating: a deleted account never lost its
 * memberships, so this puts it back exactly where it was, while reactivating a
 * deactivated one gives back an account with no communities. */
export const useOperatorRestoreUser = (options?: MutationOpts<OperatorUserRead, number>) =>
  useApiMutation<OperatorUserRead, number>(
    {
      mutationFn: (userId) => restoreDeletedUserApiV1OperatorUsersUserIdRestorePost(userId),
      invalidate: () => invalidate(q.operatorUsers()),
    },
    options
  );

type SetUsernameVars = { userId: number; username: string };

/** Change someone's username (``content.moderate``). The number is not the
 *  moderator's to choose; the server keeps the one they have. */
export const useOperatorSetUsername = (options?: MutationOpts<OperatorUserRead, SetUsernameVars>) =>
  useApiMutation<OperatorUserRead, SetUsernameVars>(
    {
      mutationFn: ({ userId, username }) =>
        setUserUsernameApiV1OperatorUsersUserIdUsernamePatch(userId, { username }),
      invalidate: () => invalidate(q.operatorUsers()),
    },
    options
  );

type SetSuspensionVars = { userId: number; suspended: boolean; reason?: string };

/** Freeze an account, or let it go (``users.manage``). Takes nothing away —
 *  memberships, grants and content are all still there when it is lifted. */
export const useOperatorSetSuspension = (
  options?: MutationOpts<OperatorUserRead, SetSuspensionVars>
) =>
  useApiMutation<OperatorUserRead, SetSuspensionVars>(
    {
      mutationFn: ({ userId, suspended, reason }) =>
        setUserSuspensionApiV1OperatorUsersUserIdSuspensionPost(userId, {
          suspended,
          reason: reason || null,
        }),
      invalidate: () => invalidate(q.operatorUsers()),
    },
    options
  );

/** Let an account answer the age question again (``users.age_unblock``).
 *  For the case that is nearly all of them: a mistyped year. It clears the
 *  record that the question was answered and nothing else — the date was never
 *  kept, so there is nothing else to clear. */
export const useOperatorClearAgeBlock = (options?: MutationOpts<OperatorUserRead, number>) =>
  useApiMutation<OperatorUserRead, number>(
    {
      mutationFn: (userId) => clearAgeBlockApiV1OperatorUsersUserIdAgeBlockDelete(userId),
      invalidate: () => invalidate(q.operatorUsers()),
    },
    options
  );

/** Turn an account's password and code sign-in back on after wrong answers
 *  turned it off (``users.manage``). */
export const useOperatorLiftSignInLock = (options?: MutationOpts<OperatorUserRead, number>) =>
  useApiMutation<OperatorUserRead, number>(
    {
      mutationFn: (userId) => liftSignInLockApiV1OperatorUsersUserIdSignInLockDelete(userId),
      invalidate: () => invalidate(q.operatorUsers()),
    },
    options
  );

/** Take down somebody's profile picture (``content.moderate``). Removal only —
 *  there is no route by which one account sets another's picture. */
export const useOperatorRemoveAvatar = (options?: MutationOpts<void, number>) =>
  useApiMutation<void, number>(
    {
      mutationFn: (userId) => removeUserAvatarApiV1OperatorUsersUserIdAvatarDelete(userId),
      invalidate: () => invalidate(q.operatorUsers()),
    },
    options
  );

type ExportPlatformUsersVars = {
  params: ExportPlatformUsersCsvApiV1OperatorUsersExportCsvGetParams;
  filename: string;
};

/** Download the platform users CSV from the backend and trigger a browser save. */
export const useExportPlatformUsersCsv = (options?: MutationOpts<void, ExportPlatformUsersVars>) =>
  useApiMutation<void, ExportPlatformUsersVars>(
    {
      mutationFn: async ({ params, filename }) => {
        const blob = (await exportPlatformUsersCsvApiV1OperatorUsersExportCsvGet(params, {
          responseType: "blob",
          // FastAPI expects ?user_id=1&user_id=2; axios's default `[]` suffix gets ignored.
          paramsSerializer: { indexes: null },
        })) as Blob;
        downloadBlob(blob, filename);
      },
    },
    options
  );

/** Update a user's platform role (operator endpoint). */
export const useOperatorUpdatePlatformRole = (
  options?: MutationOpts<OperatorUserRead, { userId: number; role: UserRole }>
) =>
  useApiMutation<OperatorUserRead, { userId: number; role: UserRole }>(
    {
      mutationFn: ({ userId, role }) =>
        updatePlatformRoleApiV1OperatorUsersUserIdPlatformRolePatch(userId, {
          role,
        } as Parameters<typeof updatePlatformRoleApiV1OperatorUsersUserIdPlatformRolePatch>[1]),
      invalidate: () => invalidate(q.operatorUsers()),
    },
    options
  );
