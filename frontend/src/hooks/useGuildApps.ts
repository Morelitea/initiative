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
  getListGuildAppsApiV1GGuildIdAppsGetQueryKey,
  installGuildAppApiV1GGuildIdAppsPost,
  listGuildAppsApiV1GGuildIdAppsGet,
  uninstallGuildAppApiV1GGuildIdAppsAppIdDelete,
  updateGuildAppApiV1GGuildIdAppsAppIdPatch,
} from "@/api/generated/apps/apps";
import type {
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

const appsKey = (guildId: number) => getListGuildAppsApiV1GGuildIdAppsGetQueryKey(guildId);

export const useGuildApps = (options?: QueryOpts<GuildAppListResponse>) => {
  const guildId = useActiveGuildId();
  return useQuery<GuildAppListResponse>({
    queryKey: appsKey(guildId),
    queryFn: () => listGuildAppsApiV1GGuildIdAppsGet(guildId),
    ...options,
  });
};

export const useInstallGuildApp = (options?: MutationOpts<GuildAppRead, GuildAppInstall>) => {
  return useGuildMutation<GuildAppRead, GuildAppInstall>(
    {
      mutationFn: (guildId, data) => installGuildAppApiV1GGuildIdAppsPost(guildId, data),
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
        updateGuildAppApiV1GGuildIdAppsAppIdPatch(guildId, appId, data),
      invalidate: () => invalidate(q.apps()),
      errorKey: "apps:error",
    },
    options
  );
};

export const useUninstallGuildApp = (options?: MutationOpts<void, number>) => {
  return useGuildMutation<void, number>(
    {
      mutationFn: (guildId, appId) => uninstallGuildAppApiV1GGuildIdAppsAppIdDelete(guildId, appId),
      invalidate: () => invalidate(q.apps()),
      errorKey: "apps:error",
    },
    options
  );
};
