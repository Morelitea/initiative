/**
 * One installed app, its connections, and the actions that change them.
 *
 * The detail read is per viewer: a member's own connect state comes back on
 * their request and nobody else's does, so there is no client-side filtering to
 * get wrong. Every mutation invalidates both this app and the guild's app list,
 * because a connection change can flip whether the install still needs
 * configuring — which the list shows.
 */

import { keepPreviousData, useMutation, useQuery } from "@tanstack/react-query";

import {
  blockMemberConnectionApiV1CGuildIdAppsAppIdMembersUserIdConnectionsConnectionIdBlockPost,
  connectGuildAppApiV1CGuildIdAppsAppIdConnectionsConnectionIdConnectPost,
  declineGuildAppUpgradeApiV1CGuildIdAppsAppIdUpgradeDeclinePost,
  disconnectGuildAppApiV1CGuildIdAppsAppIdConnectionsConnectionIdDelete,
  getGuildAppApiV1CGuildIdAppsAppIdGet,
  grantMyConsentApiV1CGuildIdAppsAppIdConsentsConsentIdPut,
  listGuildAppMembersApiV1CGuildIdAppsAppIdMembersGet,
  revokeAllMemberConnectionsApiV1CGuildIdAppsAppIdRevokeAllPost,
  revokeAllMemberConsentsApiV1CGuildIdAppsAppIdConsentsRevokeAllPost,
  revokeMemberConnectionApiV1CGuildIdAppsAppIdMembersUserIdConnectionsConnectionIdDelete,
  revokeMemberConsentsApiV1CGuildIdAppsAppIdMembersUserIdConsentsDelete,
  revokeMyConsentApiV1CGuildIdAppsAppIdConsentsConsentIdDelete,
  unblockMemberConnectionApiV1CGuildIdAppsAppIdMembersUserIdConnectionsConnectionIdBlockDelete,
  updateGuildAppConfigApiV1CGuildIdAppsAppIdConfigPut,
  upgradeGuildAppApiV1CGuildIdAppsAppIdUpgradePost,
} from "@/api/generated/apps/apps";
import type {
  ConsentAccess,
  GuildAppConfigUpdateValues,
  GuildAppConnectStart,
  GuildAppConsentRead,
  GuildAppDetail,
  GuildAppMembersResponse,
  GuildAppUpgrade,
} from "@/api/generated/initiativeAPI.schemas";
import { invalidate, q } from "@/api/query-keys";
import { useActiveGuildId } from "@/hooks/useActiveGuildId";

export const guildAppDetailKey = (guildId: number, appId: number) =>
  ["guild-app", guildId, appId] as const;

export const guildAppMembersKey = (guildId: number, appId: number) =>
  ["guild-app-members", guildId, appId] as const;

export const useGuildAppDetail = (appId: number) => {
  const guildId = useActiveGuildId();
  return useQuery<GuildAppDetail>({
    queryKey: guildAppDetailKey(guildId, appId),
    queryFn: () => getGuildAppApiV1CGuildIdAppsAppIdGet(guildId, appId),
  });
};

/** Guild admins only; the server refuses everyone else. */
/** One page of the members who connected to the app or answered it. */
export const useGuildAppMembers = (appId: number, page: number, enabled: boolean) => {
  const guildId = useActiveGuildId();
  return useQuery<GuildAppMembersResponse>({
    queryKey: [...guildAppMembersKey(guildId, appId), page],
    queryFn: () => listGuildAppMembersApiV1CGuildIdAppsAppIdMembersGet(guildId, appId, { page }),
    placeholderData: keepPreviousData,
    enabled,
  });
};

// Every mutation below refreshes the same three reads through the shared
// `() => invalidate(q.apps())`, so a connection change cannot leave the settings page, the
// Members view and the sidebar disagreeing about what is configured — and a
// write from here refreshes exactly what a frame off the realtime bus does.

/** Values keyed by connection, then field. A key sent as `null` clears it; a
 *  key left out is untouched. */
export const useUpdateAppConfig = (appId: number) => {
  const guildId = useActiveGuildId();
  return useMutation<GuildAppDetail, unknown, GuildAppConfigUpdateValues>({
    mutationFn: (values) =>
      updateGuildAppConfigApiV1CGuildIdAppsAppIdConfigPut(guildId, appId, { values }),
    onSuccess: () => invalidate(q.apps()),
  });
};

/** Apply the offered version; pass the seat's consent when it asks for more. */
export const useUpgradeApp = (appId: number) => {
  const guildId = useActiveGuildId();
  return useMutation<GuildAppDetail, unknown, GuildAppUpgrade | undefined>({
    mutationFn: (consent) =>
      upgradeGuildAppApiV1CGuildIdAppsAppIdUpgradePost(guildId, appId, consent),
    // Refreshed on failure too: a refusal means the offer moved, and the panel
    // should show what is offered now.
    onSettled: () => invalidate(q.apps()),
  });
};

/** Keep the pinned version and stop being asked about this one. */
export const useDeclineAppUpgrade = (appId: number) => {
  const guildId = useActiveGuildId();
  return useMutation<GuildAppDetail, unknown, string>({
    mutationFn: (version) =>
      declineGuildAppUpgradeApiV1CGuildIdAppsAppIdUpgradeDeclinePost(guildId, appId, { version }),
    onSettled: () => invalidate(q.apps()),
  });
};

export const useConnectApp = (appId: number) => {
  const guildId = useActiveGuildId();
  return useMutation<GuildAppConnectStart, unknown, string>({
    mutationFn: (connectionId) =>
      connectGuildAppApiV1CGuildIdAppsAppIdConnectionsConnectionIdConnectPost(
        guildId,
        appId,
        connectionId
      ),
    onSuccess: () => invalidate(q.apps()),
  });
};

export const useDisconnectApp = (appId: number) => {
  const guildId = useActiveGuildId();
  return useMutation<void, unknown, string>({
    mutationFn: (connectionId) =>
      disconnectGuildAppApiV1CGuildIdAppsAppIdConnectionsConnectionIdDelete(
        guildId,
        appId,
        connectionId
      ),
    onSuccess: () => invalidate(q.apps()),
  });
};

export interface MemberConnectionTarget {
  userId: number;
  connectionId: string;
}

export const useRevokeMemberConnection = (appId: number) => {
  const guildId = useActiveGuildId();
  return useMutation<void, unknown, MemberConnectionTarget>({
    mutationFn: ({ userId, connectionId }) =>
      revokeMemberConnectionApiV1CGuildIdAppsAppIdMembersUserIdConnectionsConnectionIdDelete(
        guildId,
        appId,
        userId,
        connectionId
      ),
    onSuccess: () => invalidate(q.apps()),
  });
};

export const useBlockMemberConnection = (appId: number) => {
  const guildId = useActiveGuildId();
  return useMutation<void, unknown, MemberConnectionTarget & { blocked: boolean }>({
    // One mutation for both directions: the button is a toggle, and splitting
    // it would mean two hooks that must stay in step about what "blocked" means.
    mutationFn: ({ userId, connectionId, blocked }) =>
      blocked
        ? unblockMemberConnectionApiV1CGuildIdAppsAppIdMembersUserIdConnectionsConnectionIdBlockDelete(
            guildId,
            appId,
            userId,
            connectionId
          )
        : blockMemberConnectionApiV1CGuildIdAppsAppIdMembersUserIdConnectionsConnectionIdBlockPost(
            guildId,
            appId,
            userId,
            connectionId
          ),
    onSuccess: () => invalidate(q.apps()),
  });
};

export const useRevokeAllConnections = (appId: number) => {
  const guildId = useActiveGuildId();
  return useMutation<void, unknown, void>({
    mutationFn: () => revokeAllMemberConnectionsApiV1CGuildIdAppsAppIdRevokeAllPost(guildId, appId),
    onSuccess: () => invalidate(q.apps()),
  });
};

// --- acting as a member ------------------------------------------------------

/** A guild admin ending every answer one member gave. There is deliberately
 *  no counterpart that gives one — governance runs one way here. */
export const useRevokeMemberConsents = (appId: number) => {
  const guildId = useActiveGuildId();
  return useMutation<void, unknown, number>({
    mutationFn: (userId) =>
      revokeMemberConsentsApiV1CGuildIdAppsAppIdMembersUserIdConsentsDelete(guildId, appId, userId),
    onSuccess: () => invalidate(q.apps()),
  });
};

/** Stop the app acting as anybody, without uninstalling it. */
export const useRevokeAllConsents = (appId: number) => {
  const guildId = useActiveGuildId();
  return useMutation<void, unknown, void>({
    mutationFn: () =>
      revokeAllMemberConsentsApiV1CGuildIdAppsAppIdConsentsRevokeAllPost(guildId, appId),
    onSuccess: () => invalidate(q.apps()),
  });
};

export interface ConsentAnswer {
  consentId: number;
  access: ConsentAccess;
}

/** Answer one of the app's requests to act as you. */
export const useGrantAppConsent = (appId: number) => {
  const guildId = useActiveGuildId();
  return useMutation<GuildAppConsentRead, unknown, ConsentAnswer>({
    mutationFn: ({ consentId, access }) =>
      grantMyConsentApiV1CGuildIdAppsAppIdConsentsConsentIdPut(guildId, appId, consentId, {
        access,
      }),
    onSuccess: () => invalidate(q.apps()),
  });
};

/** Decline one, or withdraw what you allowed. */
export const useRevokeAppConsent = (appId: number) => {
  const guildId = useActiveGuildId();
  return useMutation<void, unknown, number>({
    mutationFn: (consentId) =>
      revokeMyConsentApiV1CGuildIdAppsAppIdConsentsConsentIdDelete(guildId, appId, consentId),
    onSuccess: () => invalidate(q.apps()),
  });
};
