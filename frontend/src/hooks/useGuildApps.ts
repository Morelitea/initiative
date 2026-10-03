/**
 * Apps installed in the current guild.
 *
 * Every member reads this — the sidebar has to know what is there — while
 * installing, renaming, disabling and removing are guild-admin actions the
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
import { useActiveGuildId } from "@/hooks/useActiveGuildId";
import { useGuildMutation } from "@/hooks/useApiMutation";
import type { MutationOpts } from "@/types/mutation";
import type { QueryOpts } from "@/types/query";

const appsKey = (guildId: number) => getListCommunityAppsQueryKey(guildId);

export const useGuildApps = (options?: QueryOpts<CommunityAppListResponse>) => {
  const guildId = useActiveGuildId();
  return useQuery<CommunityAppListResponse>({
    queryKey: appsKey(guildId),
    queryFn: () => listCommunityApps(guildId),
    ...options,
  });
};

export const useInstallGuildApp = (
  options?: MutationOpts<CommunityAppRead, CommunityAppInstall>
) => {
  return useGuildMutation<CommunityAppRead, CommunityAppInstall>(
    {
      mutationFn: (guildId, data) => installCommunityApp(guildId, data),
      invalidate: () => invalidate(q.apps()),
      errorKey: "apps:error",
    },
    options
  );
};

export const useUpdateGuildApp = (
  appId: number,
  options?: MutationOpts<CommunityAppRead, CommunityAppUpdate>
) => {
  return useGuildMutation<CommunityAppRead, CommunityAppUpdate>(
    {
      mutationFn: (guildId, data) => updateCommunityApp(guildId, appId, data),
      invalidate: () => invalidate(q.apps()),
      errorKey: "apps:error",
    },
    options
  );
};

export const useUninstallGuildApp = (options?: MutationOpts<void, number>) => {
  return useGuildMutation<void, number>(
    {
      mutationFn: (guildId, appId) => uninstallCommunityApp(guildId, appId),
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
  return useGuildMutation<AppPlacementRead, AppPlacementRoles>(
    {
      mutationFn: (guildId, { initiativeId, roleIds }) =>
        putCommunityAppPlacement(guildId, appId, initiativeId, { role_ids: roleIds }),
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
  return useGuildMutation<CommunityAppRead, string[]>(
    {
      mutationFn: (guildId, granted) => putCommunityAppScopes(guildId, appId, { granted }),
      invalidate: () => invalidate(q.apps()),
      errorKey: "apps:scopes.error",
    },
    options
  );
};
