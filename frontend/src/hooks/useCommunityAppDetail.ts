/**
 * One installed app, its connections, and the actions that change them.
 *
 * The detail read is per viewer: a member's own connect state comes back on
 * their request and nobody else's does, so there is no client-side filtering to
 * get wrong. Every mutation invalidates both this app and the community's app list,
 * because a connection change can flip whether the install still needs
 * configuring — which the list shows.
 */

import { keepPreviousData, useMutation, useQuery } from "@tanstack/react-query";

import {
  blockMemberConnection,
  connectCommunityApp,
  declineCommunityAppUpgrade,
  disconnectCommunityApp,
  getCommunityApp,
  grantMyConsent,
  listCommunityAppMembers,
  revokeAllMemberConnections,
  revokeAllMemberConsents,
  revokeMemberConnection,
  revokeMemberConsents,
  revokeMyConsent,
  unblockMemberConnection,
  updateCommunityAppConfig,
  upgradeCommunityApp,
} from "@/api/generated/apps/apps";
import type {
  CommunityAppConfigUpdateValues,
  CommunityAppConnectStart,
  CommunityAppConsentRead,
  CommunityAppDetail,
  CommunityAppMembersResponse,
  CommunityAppUpgrade,
  ConsentAccess,
} from "@/api/generated/initiativeAPI.schemas";
import { invalidate, q } from "@/api/query-keys";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";

export const communityAppDetailKey = (communityId: number, appId: number) =>
  ["community-app", communityId, appId] as const;

export const communityAppMembersKey = (communityId: number, appId: number) =>
  ["community-app-members", communityId, appId] as const;

export const useCommunityAppDetail = (appId: number) => {
  const communityId = useActiveCommunityId();
  return useQuery<CommunityAppDetail>({
    queryKey: communityAppDetailKey(communityId, appId),
    queryFn: () => getCommunityApp(communityId, appId),
  });
};

/** Community admins only; the server refuses everyone else. */
/** One page of the members who connected to the app or answered it. */
export const useCommunityAppMembers = (appId: number, page: number, enabled: boolean) => {
  const communityId = useActiveCommunityId();
  return useQuery<CommunityAppMembersResponse>({
    queryKey: [...communityAppMembersKey(communityId, appId), page],
    queryFn: () => listCommunityAppMembers(communityId, appId, { page }),
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
  const communityId = useActiveCommunityId();
  return useMutation<CommunityAppDetail, unknown, CommunityAppConfigUpdateValues>({
    mutationFn: (values) => updateCommunityAppConfig(communityId, appId, { values }),
    onSuccess: () => invalidate(q.apps()),
  });
};

/** Apply the offered version; pass the seat's consent when it asks for more. */
export const useUpgradeApp = (appId: number) => {
  const communityId = useActiveCommunityId();
  return useMutation<CommunityAppDetail, unknown, CommunityAppUpgrade | undefined>({
    mutationFn: (consent) => upgradeCommunityApp(communityId, appId, consent),
    // Refreshed on failure too: a refusal means the offer moved, and the panel
    // should show what is offered now.
    onSettled: () => invalidate(q.apps()),
  });
};

/** Keep the pinned version and stop being asked about this one. */
export const useDeclineAppUpgrade = (appId: number) => {
  const communityId = useActiveCommunityId();
  return useMutation<CommunityAppDetail, unknown, string>({
    mutationFn: (version) => declineCommunityAppUpgrade(communityId, appId, { version }),
    onSettled: () => invalidate(q.apps()),
  });
};

export const useConnectApp = (appId: number) => {
  const communityId = useActiveCommunityId();
  return useMutation<CommunityAppConnectStart, unknown, string>({
    mutationFn: (connectionId) => connectCommunityApp(communityId, appId, connectionId),
    onSuccess: () => invalidate(q.apps()),
  });
};

export const useDisconnectApp = (appId: number) => {
  const communityId = useActiveCommunityId();
  return useMutation<void, unknown, string>({
    mutationFn: (connectionId) => disconnectCommunityApp(communityId, appId, connectionId),
    onSuccess: () => invalidate(q.apps()),
  });
};

export interface MemberConnectionTarget {
  userId: number;
  connectionId: string;
}

export const useRevokeMemberConnection = (appId: number) => {
  const communityId = useActiveCommunityId();
  return useMutation<void, unknown, MemberConnectionTarget>({
    mutationFn: ({ userId, connectionId }) =>
      revokeMemberConnection(communityId, appId, userId, connectionId),
    onSuccess: () => invalidate(q.apps()),
  });
};

export const useBlockMemberConnection = (appId: number) => {
  const communityId = useActiveCommunityId();
  return useMutation<void, unknown, MemberConnectionTarget & { blocked: boolean }>({
    // One mutation for both directions: the button is a toggle, and splitting
    // it would mean two hooks that must stay in step about what "blocked" means.
    mutationFn: ({ userId, connectionId, blocked }) =>
      blocked
        ? unblockMemberConnection(communityId, appId, userId, connectionId)
        : blockMemberConnection(communityId, appId, userId, connectionId),
    onSuccess: () => invalidate(q.apps()),
  });
};

export const useRevokeAllConnections = (appId: number) => {
  const communityId = useActiveCommunityId();
  return useMutation<void, unknown, void>({
    mutationFn: () => revokeAllMemberConnections(communityId, appId),
    onSuccess: () => invalidate(q.apps()),
  });
};

// --- acting as a member ------------------------------------------------------

/** A community admin ending every answer one member gave. There is deliberately
 *  no counterpart that gives one — governance runs one way here. */
export const useRevokeMemberConsents = (appId: number) => {
  const communityId = useActiveCommunityId();
  return useMutation<void, unknown, number>({
    mutationFn: (userId) => revokeMemberConsents(communityId, appId, userId),
    onSuccess: () => invalidate(q.apps()),
  });
};

/** Stop the app acting as anybody, without uninstalling it. */
export const useRevokeAllConsents = (appId: number) => {
  const communityId = useActiveCommunityId();
  return useMutation<void, unknown, void>({
    mutationFn: () => revokeAllMemberConsents(communityId, appId),
    onSuccess: () => invalidate(q.apps()),
  });
};

export interface ConsentAnswer {
  consentId: number;
  access: ConsentAccess;
}

/** Answer one of the app's requests to act as you. */
export const useGrantAppConsent = (appId: number) => {
  const communityId = useActiveCommunityId();
  return useMutation<CommunityAppConsentRead, unknown, ConsentAnswer>({
    mutationFn: ({ consentId, access }) =>
      grantMyConsent(communityId, appId, consentId, {
        access,
      }),
    onSuccess: () => invalidate(q.apps()),
  });
};

/** Decline one, or withdraw what you allowed. */
export const useRevokeAppConsent = (appId: number) => {
  const communityId = useActiveCommunityId();
  return useMutation<void, unknown, number>({
    mutationFn: (consentId) => revokeMyConsent(communityId, appId, consentId),
    onSuccess: () => invalidate(q.apps()),
  });
};
