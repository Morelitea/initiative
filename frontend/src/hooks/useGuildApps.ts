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
  getListGuildAppsApiV1CGuildIdAppsGetQueryKey,
  installGuildAppApiV1CGuildIdAppsPost,
  listGuildAppsApiV1CGuildIdAppsGet,
  putGuildAppPlacementApiV1CGuildIdAppsAppIdPlacementsInitiativeIdPut,
  putGuildAppScopesApiV1CGuildIdAppsAppIdScopesPut,
  uninstallGuildAppApiV1CGuildIdAppsAppIdDelete,
  updateGuildAppApiV1CGuildIdAppsAppIdPatch,
} from "@/api/generated/apps/apps";
import type {
  AppPlacementRead,
  GuildAppInstall,
  GuildAppListResponse,
  GuildAppRead,
  GuildAppUpdate,
} from "@/api/generated/initiativeAPI.schemas";
import { invalidate, q } from "@/api/query-keys";
import { useActiveGuildId } from "@/hooks/useActiveGuildId";
import { useGuildMutation } from "@/hooks/useApiMutation";
import type { MutationOpts } from "@/types/mutation";
import type { QueryOpts } from "@/types/query";

const appsKey = (guildId: number) => getListGuildAppsApiV1CGuildIdAppsGetQueryKey(guildId);

export const useGuildApps = (options?: QueryOpts<GuildAppListResponse>) => {
  const guildId = useActiveGuildId();
  return useQuery<GuildAppListResponse>({
    queryKey: appsKey(guildId),
    queryFn: () => listGuildAppsApiV1CGuildIdAppsGet(guildId),
    ...options,
  });
};

export const useInstallGuildApp = (options?: MutationOpts<GuildAppRead, GuildAppInstall>) => {
  return useGuildMutation<GuildAppRead, GuildAppInstall>(
    {
      mutationFn: (guildId, data) => installGuildAppApiV1CGuildIdAppsPost(guildId, data),
      invalidate: () => invalidate(q.apps()),
      errorKey: "apps:error",
    },
    options
  );
};

export const useUpdateGuildApp = (
  appId: number,
  options?: MutationOpts<GuildAppRead, GuildAppUpdate>
) => {
  return useGuildMutation<GuildAppRead, GuildAppUpdate>(
    {
      mutationFn: (guildId, data) =>
        updateGuildAppApiV1CGuildIdAppsAppIdPatch(guildId, appId, data),
      invalidate: () => invalidate(q.apps()),
      errorKey: "apps:error",
    },
    options
  );
};

export const useUninstallGuildApp = (options?: MutationOpts<void, number>) => {
  return useGuildMutation<void, number>(
    {
      mutationFn: (guildId, appId) => uninstallGuildAppApiV1CGuildIdAppsAppIdDelete(guildId, appId),
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
        putGuildAppPlacementApiV1CGuildIdAppsAppIdPlacementsInitiativeIdPut(
          guildId,
          appId,
          initiativeId,
          { role_ids: roleIds }
        ),
      invalidate: () => invalidate(q.apps()),
      errorKey: "apps:error",
    },
    options
  );
};

/** Grant the app exactly these scopes; any left out are withdrawn. */
export const useSetAppScopes = (appId: number, options?: MutationOpts<GuildAppRead, string[]>) => {
  return useGuildMutation<GuildAppRead, string[]>(
    {
      mutationFn: (guildId, granted) =>
        putGuildAppScopesApiV1CGuildIdAppsAppIdScopesPut(guildId, appId, { granted }),
      invalidate: () => invalidate(q.apps()),
      errorKey: "apps:scopes.error",
    },
    options
  );
};
