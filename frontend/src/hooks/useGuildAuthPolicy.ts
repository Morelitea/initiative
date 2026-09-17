import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  getListGuildLoginProvidersApiV1AuthGGuildIdProvidersGetQueryKey,
  getListLoginProvidersApiV1AuthProvidersGetQueryKey,
  listGuildLoginProvidersApiV1AuthGGuildIdProvidersGet,
  listLoginProvidersApiV1AuthProvidersGet,
} from "@/api/generated/auth/auth";
import {
  createGuildAuthProviderApiV1GuildsGuildIdAuthProvidersPost,
  deleteGuildAuthProviderApiV1GuildsGuildIdAuthProvidersProviderIdDelete,
  discoverGuildAuthProviderApiV1GuildsGuildIdAuthProvidersDiscoverPost,
  getListGuildAuthProvidersApiV1GuildsGuildIdAuthProvidersGetQueryKey,
  listGuildAuthProvidersApiV1GuildsGuildIdAuthProvidersGet,
  testGuildAuthProviderApiV1GuildsGuildIdAuthProvidersProviderIdTestPost,
  updateGuildAuthProviderApiV1GuildsGuildIdAuthProvidersProviderIdPatch,
} from "@/api/generated/guild-auth-providers/guild-auth-providers";
import {
  getGetGuildAuthPolicyApiV1GuildsGuildIdAuthPolicyGetQueryKey,
  getGuildAuthPolicyApiV1GuildsGuildIdAuthPolicyGet,
  setGuildApiAccessApiV1GuildsGuildIdApiAccessPut,
  setGuildAuthPolicyApiV1GuildsGuildIdAuthPolicyPut,
} from "@/api/generated/guilds/guilds";
import type {
  AuthProviderAdminRead,
  AuthProviderCreate,
  AuthProviderUpdate,
  GuildApiAccessUpdate,
  GuildAuthPolicyRead,
  GuildAuthPolicyUpdate,
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

/** The guild's own login provider registry (guild admins, per-guild auth). */
export const useGuildAuthProviders = (
  guildId: number,
  options?: QueryOpts<AuthProviderAdminRead[]>
) => {
  return useQuery<AuthProviderAdminRead[]>({
    queryKey: getListGuildAuthProvidersApiV1GuildsGuildIdAuthProvidersGetQueryKey(guildId),
    queryFn: () => listGuildAuthProvidersApiV1GuildsGuildIdAuthProvidersGet(guildId),
    enabled: guildId > 0,
    ...options,
  });
};

const useInvalidateGuildAuthProviders = (guildId: number) => {
  const queryClient = useQueryClient();
  // Registry mutations refresh both consumers of provider data: the admin
  // CRUD list and the public login listing (which feeds the policy page's
  // "sign in with it first" prompt and the step-up dialog) — otherwise a
  // freshly created provider can't be required until the cache expires.
  return () => {
    void queryClient.invalidateQueries({
      queryKey: getListGuildAuthProvidersApiV1GuildsGuildIdAuthProvidersGetQueryKey(guildId),
    });
    void queryClient.invalidateQueries({
      queryKey: getListGuildLoginProvidersApiV1AuthGGuildIdProvidersGetQueryKey(guildId),
    });
  };
};

export const useCreateGuildAuthProvider = (guildId: number) => {
  const invalidate = useInvalidateGuildAuthProviders(guildId);
  return useMutation({
    mutationFn: (data: AuthProviderCreate) =>
      createGuildAuthProviderApiV1GuildsGuildIdAuthProvidersPost(guildId, data),
    onSuccess: invalidate,
  });
};

export const useUpdateGuildAuthProvider = (guildId: number) => {
  const invalidate = useInvalidateGuildAuthProviders(guildId);
  return useMutation({
    mutationFn: ({ providerId, data }: { providerId: number; data: AuthProviderUpdate }) =>
      updateGuildAuthProviderApiV1GuildsGuildIdAuthProvidersProviderIdPatch(
        guildId,
        providerId,
        data
      ),
    onSuccess: invalidate,
  });
};

export const useDeleteGuildAuthProvider = (guildId: number) => {
  const invalidate = useInvalidateGuildAuthProviders(guildId);
  return useMutation({
    mutationFn: (providerId: number) =>
      deleteGuildAuthProviderApiV1GuildsGuildIdAuthProvidersProviderIdDelete(guildId, providerId),
    onSuccess: invalidate,
  });
};

/** Look up an address somebody is still typing. Saves nothing, so there is
 *  nothing to invalidate. */
export const useDiscoverGuildAuthProvider = (guildId: number) =>
  useMutation({
    mutationFn: ({ issuer }: { issuer: string }) =>
      discoverGuildAuthProviderApiV1GuildsGuildIdAuthProvidersDiscoverPost(guildId, { issuer }),
  });

/** Look up a saved provider, against the address on its row. */
export const useTestGuildAuthProvider = (guildId: number) =>
  useMutation({
    mutationFn: (providerId: number) =>
      testGuildAuthProviderApiV1GuildsGuildIdAuthProvidersProviderIdTestPost(guildId, providerId),
  });
