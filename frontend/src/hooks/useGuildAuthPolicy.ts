import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  getListGuildLoginProvidersApiV1AuthCGuildIdProvidersGetQueryKey,
  getListLoginProvidersApiV1AuthProvidersGetQueryKey,
  listGuildLoginProvidersApiV1AuthCGuildIdProvidersGet,
  listLoginProvidersApiV1AuthProvidersGet,
} from "@/api/generated/auth/auth";
import {
  getGetGuildAuthSettingsApiV1CommunitiesGuildIdAuthSettingsGetQueryKey,
  getGuildAuthSettingsApiV1CommunitiesGuildIdAuthSettingsGet,
  updateGuildAuthSettingsApiV1CommunitiesGuildIdAuthSettingsPatch,
} from "@/api/generated/communities/communities";
import {
  createGuildClaimRuleApiV1CommunitiesGuildIdAuthRulesPost,
  createGuildProviderConnectionApiV1CommunitiesGuildIdAuthConnectionsPost,
  deleteGuildClaimRuleApiV1CommunitiesGuildIdAuthRulesRuleIdDelete,
  deleteGuildProviderConnectionApiV1CommunitiesGuildIdAuthConnectionsConnectionIdDelete,
  getListConnectableProvidersApiV1CommunitiesGuildIdAuthConnectionsAvailableGetQueryKey,
  getListGuildClaimRulesApiV1CommunitiesGuildIdAuthRulesGetQueryKey,
  getListGuildProviderConnectionsApiV1CommunitiesGuildIdAuthConnectionsGetQueryKey,
  listConnectableProvidersApiV1CommunitiesGuildIdAuthConnectionsAvailableGet,
  listGuildClaimRulesApiV1CommunitiesGuildIdAuthRulesGet,
  listGuildProviderConnectionsApiV1CommunitiesGuildIdAuthConnectionsGet,
  updateGuildProviderConnectionApiV1CommunitiesGuildIdAuthConnectionsConnectionIdPatch,
} from "@/api/generated/community-provider-connections/community-provider-connections";
import type {
  ConnectableProviderRead,
  GuildAuthSettingsRead,
  GuildAuthSettingsUpdate,
  GuildClaimRuleCreate,
  GuildClaimRulesResponse,
  GuildProviderConnectionCreate,
  GuildProviderConnectionRead,
  GuildProviderConnectionUpdate,
  LoginProvidersResponse,
} from "@/api/generated/initiativeAPI.schemas";
import type { QueryOpts } from "@/types/query";

/** The sign-in providers the login page offers (non-secret metadata). */
export const useLoginProviders = (options?: QueryOpts<LoginProvidersResponse>) => {
  return useQuery<LoginProvidersResponse>({
    queryKey: getListLoginProvidersApiV1AuthProvidersGetQueryKey(),
    queryFn: () => listLoginProvidersApiV1AuthProvidersGet(),
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
    queryKey: getListGuildLoginProvidersApiV1AuthCGuildIdProvidersGetQueryKey(guildId),
    queryFn: () => listGuildLoginProvidersApiV1AuthCGuildIdProvidersGet(guildId),
    staleTime: 60_000,
    enabled: guildId > 0,
    ...options,
  });
};

/** The complete Authentication settings available to a settings superadmin. */
export const useGuildAuthSettings = (
  guildId: number,
  options?: QueryOpts<GuildAuthSettingsRead>
) => {
  return useQuery<GuildAuthSettingsRead>({
    queryKey: getGetGuildAuthSettingsApiV1CommunitiesGuildIdAuthSettingsGetQueryKey(guildId),
    queryFn: () => getGuildAuthSettingsApiV1CommunitiesGuildIdAuthSettingsGet(guildId),
    enabled: guildId > 0,
    ...options,
  });
};

/**
 * Change any of the seat page's rules. The response is the same read the page
 * renders from, so it goes straight into that query's cache.
 */
export const useUpdateGuildAuthSettings = (guildId: number) => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data: GuildAuthSettingsUpdate) =>
      updateGuildAuthSettingsApiV1CommunitiesGuildIdAuthSettingsPatch(guildId, data),
    onSuccess: (data) => {
      queryClient.setQueryData(
        getGetGuildAuthSettingsApiV1CommunitiesGuildIdAuthSettingsGetQueryKey(guildId),
        data
      );
    },
  });
};

/** Which of the platform's providers this community counts as its own. */
export const useGuildProviderConnections = (
  guildId: number,
  options?: QueryOpts<GuildProviderConnectionRead[]>
) => {
  return useQuery<GuildProviderConnectionRead[]>({
    queryKey:
      getListGuildProviderConnectionsApiV1CommunitiesGuildIdAuthConnectionsGetQueryKey(guildId),
    queryFn: () => listGuildProviderConnectionsApiV1CommunitiesGuildIdAuthConnectionsGet(guildId),
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
    queryKey:
      getListConnectableProvidersApiV1CommunitiesGuildIdAuthConnectionsAvailableGetQueryKey(
        guildId
      ),
    queryFn: () =>
      listConnectableProvidersApiV1CommunitiesGuildIdAuthConnectionsAvailableGet(guildId),
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
      queryKey: getListGuildClaimRulesApiV1CommunitiesGuildIdAuthRulesGetQueryKey(guildId),
    });
    void queryClient.invalidateQueries({
      queryKey:
        getListGuildProviderConnectionsApiV1CommunitiesGuildIdAuthConnectionsGetQueryKey(guildId),
    });
    void queryClient.invalidateQueries({
      queryKey:
        getListConnectableProvidersApiV1CommunitiesGuildIdAuthConnectionsAvailableGetQueryKey(
          guildId
        ),
    });
    void queryClient.invalidateQueries({
      queryKey: getListGuildLoginProvidersApiV1AuthCGuildIdProvidersGetQueryKey(guildId),
    });
  };
};

export const useConnectProvider = (guildId: number) => {
  const invalidate = useInvalidateConnections(guildId);
  return useMutation({
    mutationFn: (data: GuildProviderConnectionCreate) =>
      createGuildProviderConnectionApiV1CommunitiesGuildIdAuthConnectionsPost(guildId, data),
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
      data: GuildProviderConnectionUpdate;
    }) =>
      updateGuildProviderConnectionApiV1CommunitiesGuildIdAuthConnectionsConnectionIdPatch(
        guildId,
        connectionId,
        data
      ),
    onSuccess: invalidate,
  });
};

export const useDisconnectProvider = (guildId: number) => {
  const invalidate = useInvalidateConnections(guildId);
  return useMutation({
    mutationFn: (connectionId: number) =>
      deleteGuildProviderConnectionApiV1CommunitiesGuildIdAuthConnectionsConnectionIdDelete(
        guildId,
        connectionId
      ),
    onSuccess: invalidate,
  });
};

/** Where this community places the people its providers vouch for. */
export const useGuildClaimRules = (
  guildId: number,
  options?: QueryOpts<GuildClaimRulesResponse>
) => {
  return useQuery<GuildClaimRulesResponse>({
    queryKey: getListGuildClaimRulesApiV1CommunitiesGuildIdAuthRulesGetQueryKey(guildId),
    queryFn: () => listGuildClaimRulesApiV1CommunitiesGuildIdAuthRulesGet(guildId),
    enabled: guildId > 0,
    ...options,
  });
};

const useInvalidateClaimRules = (guildId: number) => {
  const queryClient = useQueryClient();
  return () => {
    void queryClient.invalidateQueries({
      queryKey: getListGuildClaimRulesApiV1CommunitiesGuildIdAuthRulesGetQueryKey(guildId),
    });
  };
};

export const useCreateClaimRule = (guildId: number) => {
  const invalidate = useInvalidateClaimRules(guildId);
  return useMutation({
    mutationFn: (data: GuildClaimRuleCreate) =>
      createGuildClaimRuleApiV1CommunitiesGuildIdAuthRulesPost(guildId, data),
    onSuccess: invalidate,
  });
};

export const useDeleteClaimRule = (guildId: number) => {
  const invalidate = useInvalidateClaimRules(guildId);
  return useMutation({
    mutationFn: (ruleId: number) =>
      deleteGuildClaimRuleApiV1CommunitiesGuildIdAuthRulesRuleIdDelete(guildId, ruleId),
    onSuccess: invalidate,
  });
};
