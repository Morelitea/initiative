import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";

import type {
  AccountDeletionResponse,
  DeletionEligibilityResponse,
  ExportPlatformUsersCsvParams,
  ListAllUsersParams,
  OperatorAccountCaseRead,
  OperatorDeletionEligibilityResponse,
  OperatorUserDeleteRequest,
  OperatorUserListResponse,
  OperatorUserRead,
  UserRole,
  VerificationSendResponse,
} from "@/api/generated/initiativeAPI.schemas";
import {
  checkUserDeletionEligibility,
  clearAgeBlock,
  clearProfileField,
  clearSecondFactor,
  deleteUser,
  exportPlatformUsersCsv,
  getCheckUserDeletionEligibilityQueryKey,
  getListAccountCasesQueryKey,
  getListAllUsersQueryKey,
  liftSignInLock,
  listAccountCases,
  listAllUsers,
  reactivateUser,
  removeUserAvatar,
  resendVerificationEmail,
  restoreDeletedUser,
  revokeUserApiKeys,
  setUserSuspension,
  setUserUsername,
  signUserOutEverywhere,
  triggerPasswordReset,
  updatePlatformRole,
} from "@/api/generated/operator/operator";
import {
  checkDeletionEligibility,
  getCheckDeletionEligibilityQueryKey,
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
  params: ListAllUsersParams,
  options?: QueryOpts<OperatorUserListResponse>
) => {
  return useQuery<OperatorUserListResponse>({
    queryKey: getListAllUsersQueryKey(params),
    queryFn: () => listAllUsers(params),
    placeholderData: keepPreviousData,
    ...options,
  });
};

/**
 * The open operations cases an account filed or is the subject of
 * (``users.read``): where each lives, and nothing of what it says. Pass
 * `{ enabled }` so it is only read once somebody looks.
 */
export const useOperatorAccountCases = (
  userId: number,
  options?: QueryOpts<OperatorAccountCaseRead[]>
) => {
  return useQuery<OperatorAccountCaseRead[]>({
    queryKey: getListAccountCasesQueryKey(userId),
    queryFn: () => listAccountCases(userId),
    ...options,
  });
};

/**
 * Check whether a specific user can be deleted (operator endpoint).
 *
 * Disabled by default -- call `refetch()` to trigger the eligibility check
 * on demand. The answer is cleared while `open` is false, so a dialog opened
 * again starts without the last one.
 */
export const useUserDeletionEligibility = (userId: number, open: boolean) => {
  const queryClient = useQueryClient();
  useEffect(() => {
    if (!open) {
      void queryClient.resetQueries({ queryKey: getCheckUserDeletionEligibilityQueryKey(userId) });
    }
  }, [open, queryClient, userId]);
  return useQuery<OperatorDeletionEligibilityResponse>({
    queryKey: getCheckUserDeletionEligibilityQueryKey(userId),
    queryFn: () => checkUserDeletionEligibility(userId),
    enabled: false,
  });
};

/**
 * Check whether the current (logged-in) user can delete their own account.
 *
 * Disabled by default -- call `refetch()` to trigger the eligibility check
 * on demand. The answer is cleared while `open` is false, so a dialog opened
 * again starts without the last one.
 */
export const useMyDeletionEligibility = (open: boolean) => {
  const queryClient = useQueryClient();
  useEffect(() => {
    if (!open) {
      void queryClient.resetQueries({ queryKey: getCheckDeletionEligibilityQueryKey() });
    }
  }, [open, queryClient]);
  return useQuery<DeletionEligibilityResponse>({
    queryKey: getCheckDeletionEligibilityQueryKey(),
    queryFn: () => checkDeletionEligibility(),
    enabled: false,
  });
};

// ── Mutations ─────────────────────────────────────────────────────────────────

/** The operations case an act is for, as the act's query: the case is told of
 *  the act. Nothing where no case is named. */
const forCase = (caseTaskId?: number | null) =>
  caseTaskId ? { case_task_id: caseTaskId } : undefined;

/** Delete a user account (operator endpoint). Closes over the target userId. */
export const useOperatorDeleteUser = (
  userId: number,
  options?: MutationOpts<AccountDeletionResponse, OperatorUserDeleteRequest>
) =>
  useApiMutation<AccountDeletionResponse, OperatorUserDeleteRequest>(
    {
      mutationFn: (request) => deleteUser(userId, request),
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
      mutationFn: (userId) => triggerPasswordReset(userId),
    },
    options
  );

/** Send an account's sign-up confirmation letter again (operator endpoint). */
export const useOperatorResendVerification = (
  options?: MutationOpts<VerificationSendResponse, number>
) =>
  useApiMutation<VerificationSendResponse, number>(
    {
      mutationFn: (userId) => resendVerificationEmail(userId),
    },
    options
  );

/** Reactivate a deactivated user (operator endpoint). */
export const useOperatorReactivateUser = (options?: MutationOpts<OperatorUserRead, number>) =>
  useApiMutation<OperatorUserRead, number>(
    {
      mutationFn: (userId) => reactivateUser(userId),
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
      mutationFn: (userId) => restoreDeletedUser(userId),
      invalidate: () => invalidate(q.operatorUsers()),
    },
    options
  );

type SetUsernameVars = { userId: number; username: string };

/** Change someone's username (``content.moderate``). The number is not the
 *  moderator's to choose; the server keeps the one they have. */
export const useOperatorSetUsername = (
  options?: MutationOpts<OperatorUserRead, SetUsernameVars>,
  caseTaskId?: number | null
) =>
  useApiMutation<OperatorUserRead, SetUsernameVars>(
    {
      mutationFn: ({ userId, username }) =>
        setUserUsername(userId, { username }, forCase(caseTaskId)),
      invalidate: () => invalidate(q.operatorUsers()),
    },
    options
  );

type SetSuspensionVars = { userId: number; suspended: boolean; reason?: string };

/** Freeze an account, or let it go (``users.manage``). Takes nothing away —
 *  memberships, grants and content are all still there when it is lifted. */
export const useOperatorSetSuspension = (
  options?: MutationOpts<OperatorUserRead, SetSuspensionVars>,
  caseTaskId?: number | null
) =>
  useApiMutation<OperatorUserRead, SetSuspensionVars>(
    {
      mutationFn: ({ userId, suspended, reason }) =>
        setUserSuspension(
          userId,
          {
            suspended,
            reason: reason || null,
          },
          forCase(caseTaskId)
        ),
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
      mutationFn: (userId) => clearAgeBlock(userId),
      invalidate: () => invalidate(q.operatorUsers()),
    },
    options
  );

/** Turn an account's password and code sign-in back on after wrong answers
 *  turned it off (``users.manage``). */
export const useOperatorLiftSignInLock = (options?: MutationOpts<OperatorUserRead, number>) =>
  useApiMutation<OperatorUserRead, number>(
    {
      mutationFn: (userId) => liftSignInLock(userId),
      invalidate: () => invalidate(q.operatorUsers()),
    },
    options
  );

/** Take an authenticator off an account whose holder has lost it
 *  (``users.manage``). Signs them out everywhere; they sign in with their
 *  password and set one up again. */
export const useOperatorClearSecondFactor = (options?: MutationOpts<void, number>) =>
  useApiMutation<void, number>(
    {
      mutationFn: (userId) => clearSecondFactor(userId),
      invalidate: () => invalidate(q.operatorUsers()),
    },
    options
  );

/** Switch off every API key on an account that still works (``users.manage``).
 *  The holder sees them marked off and can make new ones. */
export const useOperatorRevokeApiKeys = (
  options?: MutationOpts<OperatorUserRead, number>,
  caseTaskId?: number | null
) =>
  useApiMutation<OperatorUserRead, number>(
    {
      mutationFn: (userId) => revokeUserApiKeys(userId, forCase(caseTaskId)),
      invalidate: () => invalidate(q.operatorUsers()),
    },
    options
  );

/** Take down somebody's profile picture (``content.moderate``). Removal only —
 *  there is no route by which one account sets another's picture. */
export const useOperatorRemoveAvatar = (
  options?: MutationOpts<void, number>,
  caseTaskId?: number | null
) =>
  useApiMutation<void, number>(
    {
      mutationFn: (userId) => removeUserAvatar(userId, forCase(caseTaskId)),
      invalidate: () => invalidate(q.operatorUsers()),
    },
    options
  );

/** End every session an account has, on every device (``users.manage``). Its
 *  holder signs in again; whoever else had it does not. */
export const useOperatorSignOutEverywhere = (
  options?: MutationOpts<OperatorUserRead, number>,
  caseTaskId?: number | null
) =>
  useApiMutation<OperatorUserRead, number>(
    {
      mutationFn: (userId) => signUserOutEverywhere(userId, forCase(caseTaskId)),
      invalidate: () => invalidate(q.operatorUsers()),
    },
    options
  );

/** The parts of how an account appears to others that a moderator can clear. */
export type OperatorProfileField = "display_names" | "custom_status" | "decorations";

type ClearProfileFieldVars = { userId: number; field: OperatorProfileField };

/** Clear one part of how an account appears to others (``content.moderate``),
 *  like a picture takedown: its holder may set it again. */
export const useOperatorClearProfileField = (
  options?: MutationOpts<OperatorUserRead, ClearProfileFieldVars>,
  caseTaskId?: number | null
) =>
  useApiMutation<OperatorUserRead, ClearProfileFieldVars>(
    {
      mutationFn: ({ userId, field }) => clearProfileField(userId, field, forCase(caseTaskId)),
      invalidate: () => invalidate(q.operatorUsers()),
    },
    options
  );

type ExportPlatformUsersVars = {
  params: ExportPlatformUsersCsvParams;
  filename: string;
};

/** Download the platform users CSV from the backend and trigger a browser save. */
export const useExportPlatformUsersCsv = (options?: MutationOpts<void, ExportPlatformUsersVars>) =>
  useApiMutation<void, ExportPlatformUsersVars>(
    {
      mutationFn: async ({ params, filename }) => {
        const blob = (await exportPlatformUsersCsv(params, {
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
  options?: MutationOpts<OperatorUserRead, { userId: number; role: UserRole }>,
  caseTaskId?: number | null
) =>
  useApiMutation<OperatorUserRead, { userId: number; role: UserRole }>(
    {
      mutationFn: ({ userId, role }) =>
        updatePlatformRole(
          userId,
          { role } as Parameters<typeof updatePlatformRole>[1],
          forCase(caseTaskId)
        ),
      invalidate: () => invalidate(q.operatorUsers()),
    },
    options
  );
