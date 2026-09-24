import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  getListGuildLoginProvidersApiV1AuthCGuildIdProvidersGetQueryKey,
  getListLoginProvidersApiV1AuthProvidersGetQueryKey,
  listGuildLoginProvidersApiV1AuthCGuildIdProvidersGet,
  listLoginProvidersApiV1AuthProvidersGet,
} from "@/api/generated/auth/auth";
import {
  getGetGuildAuthPolicyApiV1CommunitiesGuildIdAuthPolicyGetQueryKey,
  getGetGuildAuthSettingsApiV1CommunitiesGuildIdAuthSettingsGetQueryKey,
  getGetGuildNotificationPolicyApiV1CommunitiesGuildIdNotificationPolicyGetQueryKey,
  getGuildAuthPolicyApiV1CommunitiesGuildIdAuthPolicyGet,
  getGuildAuthSettingsApiV1CommunitiesGuildIdAuthSettingsGet,
  getGuildNotificationPolicyApiV1CommunitiesGuildIdNotificationPolicyGet,
  setGuildApiAccessApiV1CommunitiesGuildIdApiAccessPut,
  setGuildAuthPolicyApiV1CommunitiesGuildIdAuthPolicyPut,
  setGuildNotificationPolicyApiV1CommunitiesGuildIdNotificationPolicyPut,
  setGuildSecondFactorApiV1CommunitiesGuildIdSecondFactorPut,
  setGuildSessionLimitApiV1CommunitiesGuildIdSessionLimitPut,
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
  GuildApiAccessUpdate,
  GuildAuthPolicyRead,
  GuildAuthPolicyUpdate,
  GuildAuthSettingsRead,
  GuildClaimRuleCreate,
  GuildClaimRulesResponse,
  GuildNotificationPolicyRead,
  GuildNotificationPolicyUpdate,
  GuildProviderConnectionCreate,
  GuildProviderConnectionRead,
  GuildProviderConnectionUpdate,
  GuildSecondFactorUpdate,
  GuildSessionLimitUpdate,
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

/** The guild's sign-in requirement (guild admins only). */
export const useGuildAuthPolicy = (guildId: number, options?: QueryOpts<GuildAuthPolicyRead>) => {
  return useQuery<GuildAuthPolicyRead>({
    queryKey: getGetGuildAuthPolicyApiV1CommunitiesGuildIdAuthPolicyGetQueryKey(guildId),
    queryFn: () => getGuildAuthPolicyApiV1CommunitiesGuildIdAuthPolicyGet(guildId),
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

/** Set the guild's sign-in requirement; refreshes the policy query on success. */
export const useUpdateGuildAuthPolicy = (guildId: number) => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data: GuildAuthPolicyUpdate) =>
      setGuildAuthPolicyApiV1CommunitiesGuildIdAuthPolicyPut(guildId, data),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: getGetGuildAuthPolicyApiV1CommunitiesGuildIdAuthPolicyGetQueryKey(guildId),
      });
    },
  });
};

/**
 * Whether the guild accepts personal API keys.
 *
 * The value itself rides on the guild list (`GuildRead.allow_api_keys`), so
 * there is no query of its own to invalidate — the caller refreshes the guilds
 * it already has.
 */
export const useUpdateGuildApiAccess = (guildId: number) => {
  return useMutation({
    mutationFn: (data: GuildApiAccessUpdate) =>
      setGuildApiAccessApiV1CommunitiesGuildIdApiAccessPut(guildId, data),
  });
};

/**
 * Whether the community holds its members to the twelve-hour session standard.
 * Rides on the guild list the same way API access does.
 */
export const useUpdateGuildSessionLimit = (guildId: number) => {
  return useMutation({
    mutationFn: (data: GuildSessionLimitUpdate) =>
      setGuildSessionLimitApiV1CommunitiesGuildIdSessionLimitPut(guildId, data),
  });
};

/**
 * What this community's notifications may leave the app carrying, beside what
 * the deployment already asks of every community.
 */
export const useGuildNotificationPolicy = (
  guildId: number,
  options?: QueryOpts<GuildNotificationPolicyRead>
) => {
  return useQuery<GuildNotificationPolicyRead>({
    queryKey:
      getGetGuildNotificationPolicyApiV1CommunitiesGuildIdNotificationPolicyGetQueryKey(guildId),
    queryFn: () => getGuildNotificationPolicyApiV1CommunitiesGuildIdNotificationPolicyGet(guildId),
    enabled: guildId > 0,
    ...options,
  });
};

/** Set the three answers; the page refetches to pick up the deployment's. */
export const useUpdateGuildNotificationPolicy = (guildId: number) => {
  return useMutation({
    mutationFn: (data: GuildNotificationPolicyUpdate) =>
      setGuildNotificationPolicyApiV1CommunitiesGuildIdNotificationPolicyPut(guildId, data),
  });
};

/** Whether reaching this community asks for a second factor. */
export const useUpdateGuildSecondFactor = (guildId: number) => {
  return useMutation({
    mutationFn: (data: GuildSecondFactorUpdate) =>
      setGuildSecondFactorApiV1CommunitiesGuildIdSecondFactorPut(guildId, data),
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
