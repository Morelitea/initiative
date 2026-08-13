/**
 * One installed app, its connections, and the actions that change them.
 *
 * The detail read is per viewer: a member's own connect state comes back on
 * their request and nobody else's does, so there is no client-side filtering to
 * get wrong. Every mutation invalidates both this app and the guild's app list,
 * because a connection change can flip whether the install still needs
 * configuring — which the list shows.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  type AppConfigValue,
  type AppConnectStart,
  type AppMembersResponse,
  blockMemberConnection,
  connectGuildApp,
  disconnectGuildApp,
  type GuildAppDetail,
  getGuildApp,
  getGuildAppMembers,
  revokeAllMemberConnections,
  revokeMemberConnection,
  unblockMemberConnection,
  updateGuildAppConfig,
  upgradeGuildApp,
} from "@/api/appConnections";
import { getListGuildAppsApiV1GGuildIdAppsGetQueryKey } from "@/api/generated/apps/apps";
import { useActiveGuildId } from "@/hooks/useActiveGuildId";

export const guildAppDetailKey = (guildId: number, appId: number) =>
  ["guild-app", guildId, appId] as const;

export const guildAppMembersKey = (guildId: number, appId: number) =>
  ["guild-app-members", guildId, appId] as const;

export const useGuildAppDetail = (appId: number) => {
  const guildId = useActiveGuildId();
  return useQuery<GuildAppDetail>({
    queryKey: guildAppDetailKey(guildId, appId),
    queryFn: () => getGuildApp(guildId, appId),
  });
};

/** Guild admins only; the server refuses everyone else. */
export const useGuildAppMembers = (appId: number, enabled: boolean) => {
  const guildId = useActiveGuildId();
  return useQuery<AppMembersResponse>({
    queryKey: guildAppMembersKey(guildId, appId),
    queryFn: () => getGuildAppMembers(guildId, appId),
    enabled,
  });
};

/** Every mutation below refreshes the same three reads, so a connection change
 *  cannot leave the settings page, the Members view and the sidebar disagreeing
 *  about what is configured. */
const useAppInvalidation = (appId: number) => {
  const guildId = useActiveGuildId();
  const queryClient = useQueryClient();
  return () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: guildAppDetailKey(guildId, appId) }),
      queryClient.invalidateQueries({ queryKey: guildAppMembersKey(guildId, appId) }),
      queryClient.invalidateQueries({
        queryKey: getListGuildAppsApiV1GGuildIdAppsGetQueryKey(guildId),
      }),
    ]);
};

export const useUpdateAppConfig = (appId: number) => {
  const guildId = useActiveGuildId();
  const invalidate = useAppInvalidation(appId);
  return useMutation<GuildAppDetail, unknown, Record<string, Record<string, AppConfigValue>>>({
    mutationFn: (values) => updateGuildAppConfig(guildId, appId, values),
    onSuccess: invalidate,
  });
};

export const useUpgradeApp = (appId: number) => {
  const guildId = useActiveGuildId();
  const invalidate = useAppInvalidation(appId);
  return useMutation<GuildAppDetail, unknown, void>({
    mutationFn: () => upgradeGuildApp(guildId, appId),
    onSuccess: invalidate,
  });
};

export const useConnectApp = (appId: number) => {
  const guildId = useActiveGuildId();
  const invalidate = useAppInvalidation(appId);
  return useMutation<AppConnectStart, unknown, string>({
    mutationFn: (connectionId) => connectGuildApp(guildId, appId, connectionId),
    onSuccess: invalidate,
  });
};

export const useDisconnectApp = (appId: number) => {
  const guildId = useActiveGuildId();
  const invalidate = useAppInvalidation(appId);
  return useMutation<void, unknown, string>({
    mutationFn: (connectionId) => disconnectGuildApp(guildId, appId, connectionId),
    onSuccess: invalidate,
  });
};

export interface MemberConnectionTarget {
  userId: number;
  connectionId: string;
}

export const useRevokeMemberConnection = (appId: number) => {
  const guildId = useActiveGuildId();
  const invalidate = useAppInvalidation(appId);
  return useMutation<void, unknown, MemberConnectionTarget>({
    mutationFn: ({ userId, connectionId }) =>
      revokeMemberConnection(guildId, appId, userId, connectionId),
    onSuccess: invalidate,
  });
};

export const useBlockMemberConnection = (appId: number) => {
  const guildId = useActiveGuildId();
  const invalidate = useAppInvalidation(appId);
  return useMutation<void, unknown, MemberConnectionTarget & { blocked: boolean }>({
    // One mutation for both directions: the button is a toggle, and splitting
    // it would mean two hooks that must stay in step about what "blocked" means.
    mutationFn: ({ userId, connectionId, blocked }) =>
      blocked
        ? unblockMemberConnection(guildId, appId, userId, connectionId)
        : blockMemberConnection(guildId, appId, userId, connectionId),
    onSuccess: invalidate,
  });
};

export const useRevokeAllConnections = (appId: number) => {
  const guildId = useActiveGuildId();
  const invalidate = useAppInvalidation(appId);
  return useMutation<void, unknown, void>({
    mutationFn: () => revokeAllMemberConnections(guildId, appId),
    onSuccess: invalidate,
  });
};
