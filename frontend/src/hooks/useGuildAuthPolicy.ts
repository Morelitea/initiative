import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  getListGuildLoginProvidersApiV1AuthGGuildIdProvidersGetQueryKey,
  getListLoginProvidersApiV1AuthProvidersGetQueryKey,
  listGuildLoginProvidersApiV1AuthGGuildIdProvidersGet,
  listLoginProvidersApiV1AuthProvidersGet,
} from "@/api/generated/auth/auth";
import {
  createGuildClaimRuleApiV1GuildsGuildIdAuthRulesPost,
  createGuildProviderConnectionApiV1GuildsGuildIdAuthConnectionsPost,
  deleteGuildClaimRuleApiV1GuildsGuildIdAuthRulesRuleIdDelete,
  deleteGuildProviderConnectionApiV1GuildsGuildIdAuthConnectionsConnectionIdDelete,
  getListConnectableProvidersApiV1GuildsGuildIdAuthConnectionsAvailableGetQueryKey,
  getListGuildClaimRulesApiV1GuildsGuildIdAuthRulesGetQueryKey,
  getListGuildProviderConnectionsApiV1GuildsGuildIdAuthConnectionsGetQueryKey,
  listConnectableProvidersApiV1GuildsGuildIdAuthConnectionsAvailableGet,
  listGuildClaimRulesApiV1GuildsGuildIdAuthRulesGet,
  listGuildProviderConnectionsApiV1GuildsGuildIdAuthConnectionsGet,
  updateGuildProviderConnectionApiV1GuildsGuildIdAuthConnectionsConnectionIdPatch,
} from "@/api/generated/guild-provider-connections/guild-provider-connections";
import {
  getGetGuildAuthPolicyApiV1GuildsGuildIdAuthPolicyGetQueryKey,
  getGetGuildAuthSettingsApiV1GuildsGuildIdAuthSettingsGetQueryKey,
  getGuildAuthPolicyApiV1GuildsGuildIdAuthPolicyGet,
  getGuildAuthSettingsApiV1GuildsGuildIdAuthSettingsGet,
  setGuildApiAccessApiV1GuildsGuildIdApiAccessPut,
  setGuildAuthPolicyApiV1GuildsGuildIdAuthPolicyPut,
  setGuildSessionLimitApiV1GuildsGuildIdSessionLimitPut,
} from "@/api/generated/guilds/guilds";
import type {
  ConnectableProviderRead,
  GuildApiAccessUpdate,
  GuildAuthPolicyRead,
  GuildAuthPolicyUpdate,
  GuildAuthSettingsRead,
  GuildClaimRuleCreate,
  GuildClaimRulesResponse,
  GuildProviderConnectionCreate,
  GuildProviderConnectionRead,
  GuildProviderConnectionUpdate,
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
    queryKey: getListGuildLoginProvidersApiV1AuthGGuildIdProvidersGetQueryKey(guildId),
    queryFn: () => listGuildLoginProvidersApiV1AuthGGuildIdProvidersGet(guildId),
    staleTime: 60_000,
    enabled: guildId > 0,
    ...options,
  });
};

/** The guild's sign-in requirement (guild admins only). */
export const useGuildAuthPolicy = (guildId: number, options?: QueryOpts<GuildAuthPolicyRead>) => {
  return useQuery<GuildAuthPolicyRead>({
    queryKey: getGetGuildAuthPolicyApiV1GuildsGuildIdAuthPolicyGetQueryKey(guildId),
    queryFn: () => getGuildAuthPolicyApiV1GuildsGuildIdAuthPolicyGet(guildId),
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
    queryKey: getGetGuildAuthSettingsApiV1GuildsGuildIdAuthSettingsGetQueryKey(guildId),
    queryFn: () => getGuildAuthSettingsApiV1GuildsGuildIdAuthSettingsGet(guildId),
    enabled: guildId > 0,
    ...options,
  });
};

/** Set the guild's sign-in requirement; refreshes the policy query on success. */
export const useUpdateGuildAuthPolicy = (guildId: number) => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data: GuildAuthPolicyUpdate) =>
      setGuildAuthPolicyApiV1GuildsGuildIdAuthPolicyPut(guildId, data),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: getGetGuildAuthPolicyApiV1GuildsGuildIdAuthPolicyGetQueryKey(guildId),
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
      setGuildApiAccessApiV1GuildsGuildIdApiAccessPut(guildId, data),
  });
};

/**
 * Whether the community holds its members to the twelve-hour session standard.
 * Rides on the guild list the same way API access does.
 */
export const useUpdateGuildSessionLimit = (guildId: number) => {
  return useMutation({
    mutationFn: (data: GuildSessionLimitUpdate) =>
      setGuildSessionLimitApiV1GuildsGuildIdSessionLimitPut(guildId, data),
  });
};

/** Which of the platform's providers this community counts as its own. */
export const useGuildProviderConnections = (
  guildId: number,
  options?: QueryOpts<GuildProviderConnectionRead[]>
) => {
  return useQuery<GuildProviderConnectionRead[]>({
    queryKey: getListGuildProviderConnectionsApiV1GuildsGuildIdAuthConnectionsGetQueryKey(guildId),
    queryFn: () => listGuildProviderConnectionsApiV1GuildsGuildIdAuthConnectionsGet(guildId),
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
      getListConnectableProvidersApiV1GuildsGuildIdAuthConnectionsAvailableGetQueryKey(guildId),
    queryFn: () => listConnectableProvidersApiV1GuildsGuildIdAuthConnectionsAvailableGet(guildId),
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
  // cannot be required until the cache expires.
  return () => {
    void queryClient.invalidateQueries({
      queryKey:
        getListGuildProviderConnectionsApiV1GuildsGuildIdAuthConnectionsGetQueryKey(guildId),
    });
    void queryClient.invalidateQueries({
      queryKey:
        getListConnectableProvidersApiV1GuildsGuildIdAuthConnectionsAvailableGetQueryKey(guildId),
    });
    void queryClient.invalidateQueries({
      queryKey: getListGuildLoginProvidersApiV1AuthGGuildIdProvidersGetQueryKey(guildId),
    });
  };
};

export const useConnectProvider = (guildId: number) => {
  const invalidate = useInvalidateConnections(guildId);
  return useMutation({
    mutationFn: (data: GuildProviderConnectionCreate) =>
      createGuildProviderConnectionApiV1GuildsGuildIdAuthConnectionsPost(guildId, data),
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
      updateGuildProviderConnectionApiV1GuildsGuildIdAuthConnectionsConnectionIdPatch(
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
      deleteGuildProviderConnectionApiV1GuildsGuildIdAuthConnectionsConnectionIdDelete(
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
    queryKey: getListGuildClaimRulesApiV1GuildsGuildIdAuthRulesGetQueryKey(guildId),
    queryFn: () => listGuildClaimRulesApiV1GuildsGuildIdAuthRulesGet(guildId),
    enabled: guildId > 0,
    ...options,
  });
};

const useInvalidateClaimRules = (guildId: number) => {
  const queryClient = useQueryClient();
  return () => {
    void queryClient.invalidateQueries({
      queryKey: getListGuildClaimRulesApiV1GuildsGuildIdAuthRulesGetQueryKey(guildId),
    });
  };
};

export const useCreateClaimRule = (guildId: number) => {
  const invalidate = useInvalidateClaimRules(guildId);
  return useMutation({
    mutationFn: (data: GuildClaimRuleCreate) =>
      createGuildClaimRuleApiV1GuildsGuildIdAuthRulesPost(guildId, data),
    onSuccess: invalidate,
  });
};

export const useDeleteClaimRule = (guildId: number) => {
  const invalidate = useInvalidateClaimRules(guildId);
  return useMutation({
    mutationFn: (ruleId: number) =>
      deleteGuildClaimRuleApiV1GuildsGuildIdAuthRulesRuleIdDelete(guildId, ruleId),
    onSuccess: invalidate,
  });
};
