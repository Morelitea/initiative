/**
 * Apps installed in the current community.
 *
 * Every member reads this — the sidebar has to know what is there — while
 * installing, renaming, disabling and removing are community-admin actions the
 * server enforces. The UI mirrors that by hiding the affordances, not by
 * deciding it.
 */

import { useQuery } from "@tanstack/react-query";

import {
  getListCommunityAppsQueryKey,
  installCommunityApp,
  listCommunityApps,
  putCommunityAppPlacement,
  putCommunityAppScopes,
  uninstallCommunityApp,
  updateCommunityApp,
} from "@/api/generated/apps/apps";
import type {
  AppPlacementRead,
  CommunityAppInstall,
  CommunityAppListResponse,
  CommunityAppRead,
  CommunityAppUpdate,
} from "@/api/generated/initiativeAPI.schemas";
import { invalidate, q } from "@/api/query-keys";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { useCommunityMutation } from "@/hooks/useApiMutation";
import type { MutationOpts } from "@/types/mutation";
import type { QueryOpts } from "@/types/query";

const appsKey = (communityId: number) => getListCommunityAppsQueryKey(communityId);

export const useCommunityApps = (options?: QueryOpts<CommunityAppListResponse>) => {
  const communityId = useActiveCommunityId();
  return useQuery<CommunityAppListResponse>({
    queryKey: appsKey(communityId),
    queryFn: () => listCommunityApps(communityId),
    ...options,
  });
};

export const useInstallCommunityApp = (
  options?: MutationOpts<CommunityAppRead, CommunityAppInstall>
) => {
  return useCommunityMutation<CommunityAppRead, CommunityAppInstall>(
    {
      mutationFn: (communityId, data) => installCommunityApp(communityId, data),
      invalidate: () => invalidate(q.apps()),
      errorKey: "apps:error",
    },
    options
  );
};

export const useUpdateCommunityApp = (
  appId: number,
  options?: MutationOpts<CommunityAppRead, CommunityAppUpdate>
) => {
  return useCommunityMutation<CommunityAppRead, CommunityAppUpdate>(
    {
      mutationFn: (communityId, data) => updateCommunityApp(communityId, appId, data),
      invalidate: () => invalidate(q.apps()),
      errorKey: "apps:error",
    },
    options
  );
};

export const useUninstallCommunityApp = (options?: MutationOpts<void, number>) => {
  return useCommunityMutation<void, number>(
    {
      mutationFn: (communityId, appId) => uninstallCommunityApp(communityId, appId),
      invalidate: () => invalidate(q.apps()),
      errorKey: "apps:error",
    },
    options
  );
};

export interface AppPlacementRoles {
  initiativeId: number;
  roleIds: number[];
}

/** Place the app in one initiative with exactly these roles. */
export const useSetAppPlacementRoles = (
  appId: number,
  options?: MutationOpts<AppPlacementRead, AppPlacementRoles>
) => {
  return useCommunityMutation<AppPlacementRead, AppPlacementRoles>(
    {
      mutationFn: (communityId, { initiativeId, roleIds }) =>
        putCommunityAppPlacement(communityId, appId, initiativeId, { role_ids: roleIds }),
      invalidate: () => invalidate(q.apps()),
      errorKey: "apps:error",
    },
    options
  );
};

/** Grant the app exactly these scopes; any left out are withdrawn. */
export const useSetAppScopes = (
  appId: number,
  options?: MutationOpts<CommunityAppRead, string[]>
) => {
  return useCommunityMutation<CommunityAppRead, string[]>(
    {
      mutationFn: (communityId, granted) => putCommunityAppScopes(communityId, appId, { granted }),
      invalidate: () => invalidate(q.apps()),
      errorKey: "apps:scopes.error",
    },
    options
  );
};
