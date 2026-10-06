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
  getListCommunityPluginsQueryKey,
  installCommunityPlugin,
  listCommunityPlugins,
  putCommunityPluginPlacement,
  putCommunityPluginScopes,
  uninstallCommunityPlugin,
  updateCommunityPlugin,
} from "@/api/generated/plugins/plugins";
import type {
  PluginPlacementRead,
  CommunityPluginInstall,
  CommunityPluginListResponse,
  CommunityPluginRead,
  CommunityPluginUpdate,
} from "@/api/generated/initiativeAPI.schemas";
import { invalidate, q } from "@/api/query-keys";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { useCommunityMutation } from "@/hooks/useApiMutation";
import type { MutationOpts } from "@/types/mutation";
import type { QueryOpts } from "@/types/query";

const pluginsKey = (communityId: number) => getListCommunityPluginsQueryKey(communityId);

export const useCommunityPlugins = (options?: QueryOpts<CommunityPluginListResponse>) => {
  const communityId = useActiveCommunityId();
  return useQuery<CommunityPluginListResponse>({
    queryKey: pluginsKey(communityId),
    queryFn: () => listCommunityPlugins(communityId),
    ...options,
  });
};

export const useInstallCommunityPlugin = (
  options?: MutationOpts<CommunityPluginRead, CommunityPluginInstall>
) => {
  return useCommunityMutation<CommunityPluginRead, CommunityPluginInstall>(
    {
      mutationFn: (communityId, data) => installCommunityPlugin(communityId, data),
      invalidate: () => invalidate(q.apps()),
      errorKey: "apps:error",
    },
    options
  );
};

export const useUpdateCommunityPlugin = (
  pluginId: number,
  options?: MutationOpts<CommunityPluginRead, CommunityPluginUpdate>
) => {
  return useCommunityMutation<CommunityPluginRead, CommunityPluginUpdate>(
    {
      mutationFn: (communityId, data) => updateCommunityPlugin(communityId, pluginId, data),
      invalidate: () => invalidate(q.apps()),
      errorKey: "apps:error",
    },
    options
  );
};

export const useUninstallCommunityPlugin = (options?: MutationOpts<void, number>) => {
  return useCommunityMutation<void, number>(
    {
      mutationFn: (communityId, pluginId) => uninstallCommunityPlugin(communityId, pluginId),
      invalidate: () => invalidate(q.apps()),
      errorKey: "apps:error",
    },
    options
  );
};

export interface PluginPlacementRoles {
  initiativeId: number;
  roleIds: number[];
}

/** Place the app in one initiative with exactly these roles. */
export const useSetPluginPlacementRoles = (
  pluginId: number,
  options?: MutationOpts<PluginPlacementRead, PluginPlacementRoles>
) => {
  return useCommunityMutation<PluginPlacementRead, PluginPlacementRoles>(
    {
      mutationFn: (communityId, { initiativeId, roleIds }) =>
        putCommunityPluginPlacement(communityId, pluginId, initiativeId, { role_ids: roleIds }),
      invalidate: () => invalidate(q.apps()),
      errorKey: "apps:error",
    },
    options
  );
};

/** Grant the app exactly these scopes; any left out are withdrawn. */
export const useSetPluginScopes = (
  pluginId: number,
  options?: MutationOpts<CommunityPluginRead, string[]>
) => {
  return useCommunityMutation<CommunityPluginRead, string[]>(
    {
      mutationFn: (communityId, granted) => putCommunityPluginScopes(communityId, pluginId, { granted }),
      invalidate: () => invalidate(q.apps()),
      errorKey: "apps:scopes.error",
    },
    options
  );
};
