import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  getListCommunityLoginProvidersQueryKey,
  getListLoginProvidersQueryKey,
  listCommunityLoginProviders,
  listLoginProviders,
} from "@/api/generated/auth/auth";
import {
  getCommunityAuthSettings,
  getGetCommunityAuthSettingsQueryKey,
  updateCommunityAuthSettings,
} from "@/api/generated/communities/communities";
import {
  createCommunityClaimRule,
  createCommunityProviderConnection,
  deleteCommunityClaimRule,
  deleteCommunityProviderConnection,
  getListCommunityClaimRulesQueryKey,
  getListCommunityProviderConnectionsQueryKey,
  getListConnectableProvidersQueryKey,
  listCommunityClaimRules,
  listCommunityProviderConnections,
  listConnectableProviders,
  updateCommunityProviderConnection,
} from "@/api/generated/community-provider-connections/community-provider-connections";
import type {
  CommunityAuthSettingsRead,
  CommunityAuthSettingsUpdate,
  CommunityClaimRuleCreate,
  CommunityClaimRulesResponse,
  CommunityProviderConnectionCreate,
  CommunityProviderConnectionRead,
  CommunityProviderConnectionUpdate,
  ConnectableProviderRead,
  LoginProvidersResponse,
} from "@/api/generated/initiativeAPI.schemas";
import type { QueryOpts } from "@/types/query";

/** The sign-in providers the login page offers (non-secret metadata). */
export const useLoginProviders = (options?: QueryOpts<LoginProvidersResponse>) => {
  return useQuery<LoginProvidersResponse>({
    queryKey: getListLoginProvidersQueryKey(),
    queryFn: () => listLoginProviders(),
    staleTime: 60_000,
    ...options,
  });
};

/**
 * One guild's public sign-in providers (non-secret metadata with
 * guild-addressed login URLs; empty outside per-guild auth posture).
 */
export const useGuildLoginProviders = (
  guildId: number,
  options?: QueryOpts<LoginProvidersResponse>
) => {
  return useQuery<LoginProvidersResponse>({
    queryKey: getListCommunityLoginProvidersQueryKey(guildId),
    queryFn: () => listCommunityLoginProviders(guildId),
    staleTime: 60_000,
    enabled: guildId > 0,
    ...options,
  });
};

/** The complete Authentication settings available to a settings superadmin. */
export const useGuildAuthSettings = (
  guildId: number,
  options?: QueryOpts<CommunityAuthSettingsRead>
) => {
  return useQuery<CommunityAuthSettingsRead>({
    queryKey: getGetCommunityAuthSettingsQueryKey(guildId),
    queryFn: () => getCommunityAuthSettings(guildId),
    enabled: guildId > 0,
    ...options,
  });
};

/**
 * Change any of the seat page's rules, then read them all back. Two switches
 * saved together can answer out of order, so the page rereads what the server
 * holds rather than taking either answer as the latest.
 */
export const useUpdateGuildAuthSettings = (guildId: number) => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data: CommunityAuthSettingsUpdate) => updateCommunityAuthSettings(guildId, data),
    onSuccess: () =>
      queryClient.invalidateQueries({
        queryKey: getGetCommunityAuthSettingsQueryKey(guildId),
      }),
  });
};

/** Which of the platform's providers this community counts as its own. */
export const useGuildProviderConnections = (
  guildId: number,
  options?: QueryOpts<CommunityProviderConnectionRead[]>
) => {
  return useQuery<CommunityProviderConnectionRead[]>({
    queryKey: getListCommunityProviderConnectionsQueryKey(guildId),
    queryFn: () => listCommunityProviderConnections(guildId),
    enabled: guildId > 0,
    ...options,
  });
};

/** The providers this community may choose from — on offer, or already in use. */
export const useConnectableProviders = (
  guildId: number,
  options?: QueryOpts<ConnectableProviderRead[]>
) => {
  return useQuery<ConnectableProviderRead[]>({
    queryKey: getListConnectableProvidersQueryKey(guildId),
    queryFn: () => listConnectableProviders(guildId),
    enabled: guildId > 0,
    ...options,
  });
};

const useInvalidateConnections = (guildId: number) => {
  const queryClient = useQueryClient();
  // Three consumers read this: the list, the picker (a provider already
  // connected is still offered, so it has to know), and the public login
  // listing — which feeds the policy page's "sign in with it first" prompt
  // and the step-up dialog. Without the last one a freshly connected provider
  // cannot be required until the cache expires. The rules list reads it too:
  // whether the deployment's rules for a provider apply here follows the
  // connection's acceptance.
  return () => {
    void queryClient.invalidateQueries({
      queryKey: getListCommunityClaimRulesQueryKey(guildId),
    });
    void queryClient.invalidateQueries({
      queryKey: getListCommunityProviderConnectionsQueryKey(guildId),
    });
    void queryClient.invalidateQueries({
      queryKey: getListConnectableProvidersQueryKey(guildId),
    });
    void queryClient.invalidateQueries({
      queryKey: getListCommunityLoginProvidersQueryKey(guildId),
    });
  };
};

export const useConnectProvider = (guildId: number) => {
  const invalidate = useInvalidateConnections(guildId);
  return useMutation({
    mutationFn: (data: CommunityProviderConnectionCreate) =>
      createCommunityProviderConnection(guildId, data),
    onSuccess: invalidate,
  });
};

export const useUpdateProviderConnection = (guildId: number) => {
  const invalidate = useInvalidateConnections(guildId);
  return useMutation({
    mutationFn: ({
      connectionId,
      data,
    }: {
      connectionId: number;
      data: CommunityProviderConnectionUpdate;
    }) => updateCommunityProviderConnection(guildId, connectionId, data),
    onSuccess: invalidate,
  });
};

export const useDisconnectProvider = (guildId: number) => {
  const invalidate = useInvalidateConnections(guildId);
  return useMutation({
    mutationFn: (connectionId: number) => deleteCommunityProviderConnection(guildId, connectionId),
    onSuccess: invalidate,
  });
};

/** Where this community places the people its providers vouch for. */
export const useGuildClaimRules = (
  guildId: number,
  options?: QueryOpts<CommunityClaimRulesResponse>
) => {
  return useQuery<CommunityClaimRulesResponse>({
    queryKey: getListCommunityClaimRulesQueryKey(guildId),
    queryFn: () => listCommunityClaimRules(guildId),
    enabled: guildId > 0,
    ...options,
  });
};

const useInvalidateClaimRules = (guildId: number) => {
  const queryClient = useQueryClient();
  return () => {
    void queryClient.invalidateQueries({
      queryKey: getListCommunityClaimRulesQueryKey(guildId),
    });
  };
};

export const useCreateClaimRule = (guildId: number) => {
  const invalidate = useInvalidateClaimRules(guildId);
  return useMutation({
    mutationFn: (data: CommunityClaimRuleCreate) => createCommunityClaimRule(guildId, data),
    onSuccess: invalidate,
  });
};

export const useDeleteClaimRule = (guildId: number) => {
  const invalidate = useInvalidateClaimRules(guildId);
  return useMutation({
    mutationFn: (ruleId: number) => deleteCommunityClaimRule(guildId, ruleId),
    onSuccess: invalidate,
  });
};
