/**
 * One installed app, its connections, and the actions that change them.
 *
 * The detail read is per viewer: a member's own connect state comes back on
 * their request and nobody else's does, so there is no client-side filtering to
 * get wrong. Every mutation invalidates both this app and the guild's app list,
 * because a connection change can flip whether the install still needs
 * configuring — which the list shows.
 */

import { useMutation, useQuery } from "@tanstack/react-query";

import {
  type AppConfigValue,
  type AppConnectStart,
  type AppDelegation,
  type AppMembersResponse,
  blockMemberConnection,
  connectGuildApp,
  declineGuildAppUpgrade,
  disconnectGuildApp,
  type GuildAppDetail,
  getGuildApp,
  getGuildAppMembers,
  grantAppConsent,
  grantAppDelegation,
  revokeAllMemberConnections,
  revokeAllMemberDelegations,
  revokeAppConsent,
  revokeAppDelegation,
  revokeMemberConnection,
  revokeMemberDelegation,
  unblockMemberConnection,
  updateGuildAppConfig,
  upgradeGuildApp,
} from "@/api/appConnections";
import type {
  ConsentAccess,
  GuildAppConsentRead,
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

// Every mutation below refreshes the same three reads through the shared
// `() => invalidate(q.apps())`, so a connection change cannot leave the settings page, the
// Members view and the sidebar disagreeing about what is configured — and a
// write from here refreshes exactly what a frame off the realtime bus does.

export const useUpdateAppConfig = (appId: number) => {
  const guildId = useActiveGuildId();
  return useMutation<GuildAppDetail, unknown, Record<string, Record<string, AppConfigValue>>>({
    mutationFn: (values) => updateGuildAppConfig(guildId, appId, values),
    onSuccess: () => invalidate(q.apps()),
  });
};

/** Apply the offered version; pass the seat's consent when it asks for more. */
export const useUpgradeApp = (appId: number) => {
  const guildId = useActiveGuildId();
  return useMutation<GuildAppDetail, unknown, GuildAppUpgrade | undefined>({
    mutationFn: (consent) => upgradeGuildApp(guildId, appId, consent),
    // Refreshed on failure too: a refusal means the offer moved, and the panel
    // should show what is offered now.
    onSettled: () => invalidate(q.apps()),
  });
};

/** Keep the pinned version and stop being asked about this one. */
export const useDeclineAppUpgrade = (appId: number) => {
  const guildId = useActiveGuildId();
  return useMutation<GuildAppDetail, unknown, string>({
    mutationFn: (version) => declineGuildAppUpgrade(guildId, appId, version),
    onSettled: () => invalidate(q.apps()),
  });
};

export const useConnectApp = (appId: number) => {
  const guildId = useActiveGuildId();
  return useMutation<AppConnectStart, unknown, string>({
    mutationFn: (connectionId) => connectGuildApp(guildId, appId, connectionId),
    onSuccess: () => invalidate(q.apps()),
  });
};

export const useDisconnectApp = (appId: number) => {
  const guildId = useActiveGuildId();
  return useMutation<void, unknown, string>({
    mutationFn: (connectionId) => disconnectGuildApp(guildId, appId, connectionId),
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
      revokeMemberConnection(guildId, appId, userId, connectionId),
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
        ? unblockMemberConnection(guildId, appId, userId, connectionId)
        : blockMemberConnection(guildId, appId, userId, connectionId),
    onSuccess: () => invalidate(q.apps()),
  });
};

export const useRevokeAllConnections = (appId: number) => {
  const guildId = useActiveGuildId();
  return useMutation<void, unknown, void>({
    mutationFn: () => revokeAllMemberConnections(guildId, appId),
    onSuccess: () => invalidate(q.apps()),
  });
};

// --- acting as a member ------------------------------------------------------

/** Authorize the app to act as you, or change the depth of an authorization
 *  already given. Takes no user id: the caller is the subject. */
export const useGrantAppDelegation = (appId: number) => {
  const guildId = useActiveGuildId();
  return useMutation<AppDelegation, unknown, boolean>({
    mutationFn: (canWrite) => grantAppDelegation(guildId, appId, canWrite),
    onSuccess: () => invalidate(q.apps()),
  });
};

/** Withdraw your own. */
export const useRevokeAppDelegation = (appId: number) => {
  const guildId = useActiveGuildId();
  return useMutation<void, unknown, void>({
    mutationFn: () => revokeAppDelegation(guildId, appId),
    onSuccess: () => invalidate(q.apps()),
  });
};

/** A guild admin ending one member's. There is deliberately no counterpart
 *  that creates one — governance runs one way here. */
export const useRevokeMemberDelegation = (appId: number) => {
  const guildId = useActiveGuildId();
  return useMutation<void, unknown, number>({
    mutationFn: (userId) => revokeMemberDelegation(guildId, appId, userId),
    onSuccess: () => invalidate(q.apps()),
  });
};

/** Stop the app acting as anybody, without uninstalling it. */
export const useRevokeAllDelegations = (appId: number) => {
  const guildId = useActiveGuildId();
  return useMutation<void, unknown, void>({
    mutationFn: () => revokeAllMemberDelegations(guildId, appId),
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
    mutationFn: ({ consentId, access }) => grantAppConsent(guildId, appId, consentId, access),
    onSuccess: () => invalidate(q.apps()),
  });
};

/** Decline one, or withdraw what you allowed. */
export const useRevokeAppConsent = (appId: number) => {
  const guildId = useActiveGuildId();
  return useMutation<void, unknown, number>({
    mutationFn: (consentId) => revokeAppConsent(guildId, appId, consentId),
    onSuccess: () => invalidate(q.apps()),
  });
};
