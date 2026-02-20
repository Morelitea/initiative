import { useQuery, type UseQueryOptions } from "@tanstack/react-query";

import {
  listAllUsersApiV1AdminUsersGet,
  getListAllUsersApiV1AdminUsersGetQueryKey,
  getPlatformAdminCountApiV1AdminPlatformAdminCountGet,
  getGetPlatformAdminCountApiV1AdminPlatformAdminCountGetQueryKey,
  checkUserDeletionEligibilityApiV1AdminUsersUserIdDeletionEligibilityGet,
  getCheckUserDeletionEligibilityApiV1AdminUsersUserIdDeletionEligibilityGetQueryKey,
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
} from "@/api/generated/initiativeAPI.schemas";

type QueryOpts<T> = Omit<UseQueryOptions<T>, "queryKey" | "queryFn">;

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
