import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  clearProviderDefaultApiV1SettingsAuthProvidersProviderIdDefaultDelete,
  createAuthProviderApiV1SettingsAuthProvidersPost,
  deleteAuthProviderApiV1SettingsAuthProvidersProviderIdDelete,
  discoverAuthProviderApiV1SettingsAuthProvidersDiscoverPost,
  getGetProviderDefaultApiV1SettingsAuthProvidersProviderIdDefaultGetQueryKey,
  getListAuthProvidersApiV1SettingsAuthProvidersGetQueryKey,
  getProviderDefaultApiV1SettingsAuthProvidersProviderIdDefaultGet,
  listAuthProvidersApiV1SettingsAuthProvidersGet,
  setProviderDefaultApiV1SettingsAuthProvidersProviderIdDefaultPut,
  testAuthProviderApiV1SettingsAuthProvidersProviderIdTestPost,
  updateAuthProviderApiV1SettingsAuthProvidersProviderIdPatch,
} from "@/api/generated/auth-providers/auth-providers";
import type {
  AuthProviderAdminRead,
  AuthProviderCreate,
  AuthProviderProbeResult,
  AuthProviderUpdate,
  ChangelogResponse,
  CommunitySettingsResponse,
  CommunitySettingsUpdate,
  EmailSettingsResponse,
  EmailSettingsUpdate,
  FCMConfigResponse,
  GetChangelogApiV1ChangelogGetParams,
  InterfaceSettingsResponse,
  InterfaceSettingsUpdate,
  LoginMethodsUpdate,
  OIDCClaimMappingCreate,
  OIDCClaimMappingRead,
  OIDCClaimMappingUpdate,
  OIDCMappingOptionsResponse,
  OIDCMappingsResponse,
  OIDCSettingsResponse,
  PlatformAuthSettingsResponse,
  PlatformGuildStorageRead,
  PlatformGuildStorageUpdate,
  PlatformProviderDefaultRead,
  PlatformProviderDefaultUpdate,
  SecondFactorRequirementUpdate,
  SessionLifetimeUpdate,
  StorageBackfillStatusResponse,
  StorageSettingsResponse,
  StorageSettingsUpdate,
  StorageTestResponse,
} from "@/api/generated/initiativeAPI.schemas";
import {
  createOidcMappingApiV1SettingsOidcMappingsPost,
  deleteOidcMappingApiV1SettingsOidcMappingsMappingIdDelete,
  getEmailSettingsApiV1SettingsEmailGet,
  getFcmConfigApiV1SettingsFcmConfigGet,
  getGetEmailSettingsApiV1SettingsEmailGetQueryKey,
  getGetFcmConfigApiV1SettingsFcmConfigGetQueryKey,
  getGetInterfaceSettingsApiV1SettingsInterfaceGetQueryKey,
  getGetOidcMappingOptionsApiV1SettingsOidcMappingsOptionsGetQueryKey,
  getGetOidcMappingsApiV1SettingsOidcMappingsGetQueryKey,
  getGetOidcSettingsApiV1SettingsAuthGetQueryKey,
  getGetPlatformAuthSettingsApiV1SettingsAuthPlatformGetQueryKey,
  getGetStorageBackfillStatusApiV1SettingsStorageBackfillGetQueryKey,
  getGetStorageSettingsApiV1SettingsStorageGetQueryKey,
  getInterfaceSettingsApiV1SettingsInterfaceGet,
  getListPlatformGuildStorageApiV1SettingsGuildsGetQueryKey,
  getOidcMappingOptionsApiV1SettingsOidcMappingsOptionsGet,
  getOidcMappingsApiV1SettingsOidcMappingsGet,
  getOidcSettingsApiV1SettingsAuthGet,
  getPlatformAuthSettingsApiV1SettingsAuthPlatformGet,
  getStorageBackfillStatusApiV1SettingsStorageBackfillGet,
  getStorageSettingsApiV1SettingsStorageGet,
  listPlatformGuildStorageApiV1SettingsGuildsGet,
  sendTestEmailApiV1SettingsEmailTestPost,
  startStorageBackfillApiV1SettingsStorageBackfillPost,
  testStorageConnectionApiV1SettingsStorageTestPost,
  updateCommunitySettingsApiV1SettingsCommunityPut,
  updateEmailSettingsApiV1SettingsEmailPut,
  updateInterfaceSettingsApiV1SettingsInterfacePut,
  updateLoginMethodsApiV1SettingsAuthMethodsPut,
  updateOidcMappingApiV1SettingsOidcMappingsMappingIdPut,
  updatePlatformGuildStorageApiV1SettingsGuildsGuildIdPatch,
  updateSecondFactorRequirementApiV1SettingsAuthSecondFactorRequirementPut,
  updateSessionLifetimeApiV1SettingsAuthSessionLifetimePut,
  updateStorageSettingsApiV1SettingsStoragePut,
  useReadCommunitySettingsApiV1SettingsCommunityGet,
} from "@/api/generated/settings/settings";
import {
  getChangelogApiV1ChangelogGet,
  getGetChangelogApiV1ChangelogGetQueryKey,
} from "@/api/generated/version/version";
import { invalidate, q } from "@/api/query-keys";
import { useApiMutation } from "@/hooks/useApiMutation";
import type { MutationOpts } from "@/types/mutation";
import type { QueryOpts } from "@/types/query";

// ── Queries ─────────────────────────────────────────────────────────────────

export const useOidcSettings = (options?: QueryOpts<OIDCSettingsResponse>) => {
  return useQuery<OIDCSettingsResponse>({
    queryKey: getGetOidcSettingsApiV1SettingsAuthGetQueryKey(),
    queryFn: () => getOidcSettingsApiV1SettingsAuthGet(),
    ...options,
  });
};

export const useAuthProviders = (options?: QueryOpts<AuthProviderAdminRead[]>) => {
  return useQuery<AuthProviderAdminRead[]>({
    queryKey: getListAuthProvidersApiV1SettingsAuthProvidersGetQueryKey(),
    queryFn: () => listAuthProvidersApiV1SettingsAuthProvidersGet(),
    ...options,
  });
};

export const useOidcMappings = () => {
  return useQuery<OIDCMappingsResponse>({
    queryKey: getGetOidcMappingsApiV1SettingsOidcMappingsGetQueryKey(),
    queryFn: () => getOidcMappingsApiV1SettingsOidcMappingsGet(),
  });
};

export const useOidcMappingOptions = () => {
  return useQuery<OIDCMappingOptionsResponse>({
    queryKey: getGetOidcMappingOptionsApiV1SettingsOidcMappingsOptionsGetQueryKey(),
    queryFn: () => getOidcMappingOptionsApiV1SettingsOidcMappingsOptionsGet(),
  });
};

export const useEmailSettings = (options?: QueryOpts<EmailSettingsResponse>) => {
  return useQuery<EmailSettingsResponse>({
    queryKey: getGetEmailSettingsApiV1SettingsEmailGetQueryKey(),
    queryFn: () => getEmailSettingsApiV1SettingsEmailGet(),
    ...options,
  });
};

export const useStorageSettings = (options?: QueryOpts<StorageSettingsResponse>) => {
  return useQuery<StorageSettingsResponse>({
    queryKey: getGetStorageSettingsApiV1SettingsStorageGetQueryKey(),
    queryFn: () => getStorageSettingsApiV1SettingsStorageGet(),
    ...options,
  });
};

export const useStorageBackfillStatus = (options?: QueryOpts<StorageBackfillStatusResponse>) => {
  return useQuery<StorageBackfillStatusResponse>({
    queryKey: getGetStorageBackfillStatusApiV1SettingsStorageBackfillGetQueryKey(),
    queryFn: () => getStorageBackfillStatusApiV1SettingsStorageBackfillGet(),
    ...options,
  });
};

export const useInterfaceSettings = (options?: QueryOpts<InterfaceSettingsResponse>) => {
  return useQuery<InterfaceSettingsResponse>({
    queryKey: getGetInterfaceSettingsApiV1SettingsInterfaceGetQueryKey(),
    queryFn: () => getInterfaceSettingsApiV1SettingsInterfaceGet(),
    ...options,
  });
};

export const useFcmConfig = () => {
  return useQuery<FCMConfigResponse>({
    queryKey: getGetFcmConfigApiV1SettingsFcmConfigGetQueryKey(),
    queryFn: () => getFcmConfigApiV1SettingsFcmConfigGet(),
    staleTime: 5 * 60 * 1000,
  });
};

/**
 * Every guild with its storage cap, for the platform settings → Guilds tab.
 * Owner-only (`config.manage`); pass `{ enabled }` to skip the request for
 * non-owners.
 */
export const usePlatformGuilds = (options?: QueryOpts<PlatformGuildStorageRead[]>) => {
  return useQuery<PlatformGuildStorageRead[]>({
    queryKey: getListPlatformGuildStorageApiV1SettingsGuildsGetQueryKey(),
    queryFn: () => listPlatformGuildStorageApiV1SettingsGuildsGet(),
    ...options,
  });
};

export const useChangelog = (
  params: GetChangelogApiV1ChangelogGetParams,
  options?: QueryOpts<ChangelogResponse>
) => {
  return useQuery<ChangelogResponse>({
    queryKey: getGetChangelogApiV1ChangelogGetQueryKey(params),
    queryFn: () => getChangelogApiV1ChangelogGet(params),
    ...options,
  });
};

// ── Settings Mutations ──────────────────────────────────────────────────────

export const useCreateAuthProvider = (
  options?: MutationOpts<AuthProviderAdminRead, AuthProviderCreate>
) =>
  useApiMutation<AuthProviderAdminRead, AuthProviderCreate>(
    {
      mutationFn: (data) => createAuthProviderApiV1SettingsAuthProvidersPost(data),
      invalidate: () => invalidate(q.authProviders()),
    },
    options
  );

export const useUpdateAuthProvider = (
  options?: MutationOpts<AuthProviderAdminRead, { providerId: number; data: AuthProviderUpdate }>
) =>
  useApiMutation<AuthProviderAdminRead, { providerId: number; data: AuthProviderUpdate }>(
    {
      mutationFn: ({ providerId, data }) =>
        updateAuthProviderApiV1SettingsAuthProvidersProviderIdPatch(providerId, data),
      invalidate: () => invalidate(q.authProviders()),
    },
    options
  );

export const useDeleteAuthProvider = (options?: MutationOpts<void, number>) =>
  useApiMutation<void, number>(
    {
      mutationFn: (providerId) =>
        deleteAuthProviderApiV1SettingsAuthProvidersProviderIdDelete(providerId),
      invalidate: () => invalidate(q.authProviders()),
    },
    options
  );

/** Look up an address somebody is still typing. Nothing is saved, and nothing
 *  in the cache changes, so there is nothing to invalidate. */
export const useDiscoverAuthProvider = (
  options?: MutationOpts<AuthProviderProbeResult, { issuer: string }>
) =>
  useApiMutation<AuthProviderProbeResult, { issuer: string }>(
    { mutationFn: (data) => discoverAuthProviderApiV1SettingsAuthProvidersDiscoverPost(data) },
    options
  );

/** Look up a saved provider, against the address on its row. */
export const useTestAuthProvider = (options?: MutationOpts<AuthProviderProbeResult, number>) =>
  useApiMutation<AuthProviderProbeResult, number>(
    {
      mutationFn: (providerId) =>
        testAuthProviderApiV1SettingsAuthProvidersProviderIdTestPost(providerId),
    },
    options
  );

export const useUpdateInterfaceSettings = (
  options?: MutationOpts<InterfaceSettingsResponse, InterfaceSettingsUpdate>
) =>
  useApiMutation<InterfaceSettingsResponse, InterfaceSettingsUpdate>(
    {
      mutationFn: (data) =>
        updateInterfaceSettingsApiV1SettingsInterfacePut(
          data as Parameters<typeof updateInterfaceSettingsApiV1SettingsInterfacePut>[0]
        ),
      invalidate: () => invalidate(q.interfaceSettings()),
    },
    options
  );

/**
 * The three community-wide decisions, for the owner's settings page.
 *
 * The two switches are on the boot config, which is where every other page
 * reads them; the default direct-message policy is not, because nothing in the
 * SPA acts on it — the server applies it when an account is made. So it is
 * read here, behind the capability that writes it.
 */
export const useCommunitySettings = () => useReadCommunitySettingsApiV1SettingsCommunityGet();

/**
 * Turn the community directory on or off for the whole deployment (owner only).
 *
 * Invalidates the boot config, which carries the two switches every signed-in
 * page reads, and this page's own read, which carries the third decision.
 */
export const useUpdateCommunitySettings = (
  options?: MutationOpts<CommunitySettingsResponse, CommunitySettingsUpdate>
) =>
  useApiMutation<CommunitySettingsResponse, CommunitySettingsUpdate>(
    {
      mutationFn: (data) =>
        updateCommunitySettingsApiV1SettingsCommunityPut(
          data as Parameters<typeof updateCommunitySettingsApiV1SettingsCommunityPut>[0]
        ),
      invalidate: () => invalidate(q.appConfig(), q.communitySettings()),
    },
    options
  );

/**
 * Where sign-in is configured, which ways in are permitted, and what changing
 * either would cost. Owner only.
 */
export const usePlatformAuthSettings = (options?: QueryOpts<PlatformAuthSettingsResponse>) =>
  useQuery<PlatformAuthSettingsResponse>({
    queryKey: getGetPlatformAuthSettingsApiV1SettingsAuthPlatformGetQueryKey(),
    queryFn: () => getPlatformAuthSettingsApiV1SettingsAuthPlatformGet(),
    ...options,
  });

/**
 * Set which ways in the deployment permits.
 *
 * Also invalidates the boot config: the login page reads the permitted methods
 * from there to decide whether to offer the password form.
 */
export const useUpdateLoginMethods = (
  options?: MutationOpts<PlatformAuthSettingsResponse, LoginMethodsUpdate>
) =>
  useApiMutation<PlatformAuthSettingsResponse, LoginMethodsUpdate>(
    {
      mutationFn: (data) =>
        updateLoginMethodsApiV1SettingsAuthMethodsPut(
          data as Parameters<typeof updateLoginMethodsApiV1SettingsAuthMethodsPut>[0]
        ),
      invalidate: () => invalidate(q.platformAuthSettings(), q.authSettings(), q.appConfig()),
    },
    options
  );

/**
 * Set how long somebody may stay signed in before signing in again.
 *
 * Separate from how long a session may be left alone. A web session already
 * open keeps the terms it was opened under; a device token is brought under
 * the new figure now, so shortening the limit can sign a phone out.
 */
export const useUpdateSessionLifetime = (
  options?: MutationOpts<PlatformAuthSettingsResponse, SessionLifetimeUpdate>
) =>
  useApiMutation<PlatformAuthSettingsResponse, SessionLifetimeUpdate>(
    {
      mutationFn: (data) =>
        updateSessionLifetimeApiV1SettingsAuthSessionLifetimePut(
          data as Parameters<typeof updateSessionLifetimeApiV1SettingsAuthSessionLifetimePut>[0]
        ),
      invalidate: () => invalidate(q.platformAuthSettings()),
    },
    options
  );

/**
 * Set who this deployment asks to hold a second factor.
 *
 * Nobody is signed out by the change. An account the level covers is asked at
 * its next request and answers it where it stands.
 */
export const useUpdateSecondFactorRequirement = (
  options?: MutationOpts<PlatformAuthSettingsResponse, SecondFactorRequirementUpdate>
) =>
  useApiMutation<PlatformAuthSettingsResponse, SecondFactorRequirementUpdate>(
    {
      mutationFn: (data) =>
        updateSecondFactorRequirementApiV1SettingsAuthSecondFactorRequirementPut(
          data as Parameters<
            typeof updateSecondFactorRequirementApiV1SettingsAuthSecondFactorRequirementPut
          >[0]
        ),
      invalidate: () => invalidate(q.platformAuthSettings()),
    },
    options
  );

export const useUpdateEmailSettings = (
  options?: MutationOpts<EmailSettingsResponse, EmailSettingsUpdate>
) =>
  useApiMutation<EmailSettingsResponse, EmailSettingsUpdate>(
    {
      mutationFn: (data) =>
        updateEmailSettingsApiV1SettingsEmailPut(
          data as Parameters<typeof updateEmailSettingsApiV1SettingsEmailPut>[0]
        ),
      invalidate: () => invalidate(q.emailSettings()),
    },
    options
  );

export const useSendTestEmail = (
  options?: MutationOpts<void, Parameters<typeof sendTestEmailApiV1SettingsEmailTestPost>[0]>
) =>
  useApiMutation<void, Parameters<typeof sendTestEmailApiV1SettingsEmailTestPost>[0]>(
    {
      mutationFn: async (data) => {
        await sendTestEmailApiV1SettingsEmailTestPost(data);
      },
    },
    options
  );

export const useUpdateStorageSettings = (
  options?: MutationOpts<StorageSettingsResponse, StorageSettingsUpdate>
) =>
  useApiMutation<StorageSettingsResponse, StorageSettingsUpdate>(
    {
      mutationFn: (data) =>
        updateStorageSettingsApiV1SettingsStoragePut(
          data as Parameters<typeof updateStorageSettingsApiV1SettingsStoragePut>[0]
        ),
      invalidate: () => invalidate(q.storageSettings()),
    },
    options
  );

export const useTestStorageConnection = (
  options?: MutationOpts<StorageTestResponse, StorageSettingsUpdate>
) =>
  useApiMutation<StorageTestResponse, StorageSettingsUpdate>(
    {
      mutationFn: (data) =>
        testStorageConnectionApiV1SettingsStorageTestPost(
          data as Parameters<typeof testStorageConnectionApiV1SettingsStorageTestPost>[0]
        ),
    },
    options
  );

export const useStartStorageBackfill = (
  options?: MutationOpts<StorageBackfillStatusResponse, void>
) =>
  useApiMutation<StorageBackfillStatusResponse, void>(
    {
      mutationFn: () => startStorageBackfillApiV1SettingsStorageBackfillPost(),
    },
    options
  );

export const useUpdateGuildStorage = (
  options?: MutationOpts<
    PlatformGuildStorageRead,
    { guildId: number; data: PlatformGuildStorageUpdate }
  >
) =>
  useApiMutation<PlatformGuildStorageRead, { guildId: number; data: PlatformGuildStorageUpdate }>(
    {
      mutationFn: ({ guildId, data }) =>
        updatePlatformGuildStorageApiV1SettingsGuildsGuildIdPatch(
          guildId,
          data as Parameters<typeof updatePlatformGuildStorageApiV1SettingsGuildsGuildIdPatch>[1]
        ),
      invalidate: () => invalidate(q.platformGuilds()),
    },
    options
  );

// ── OIDC Claim Mapping Mutations ────────────────────────────────────────────

export const useCreateOidcMapping = (
  options?: MutationOpts<OIDCClaimMappingRead, OIDCClaimMappingCreate>
) =>
  useApiMutation<OIDCClaimMappingRead, OIDCClaimMappingCreate>(
    {
      mutationFn: (data) =>
        createOidcMappingApiV1SettingsOidcMappingsPost(
          data as Parameters<typeof createOidcMappingApiV1SettingsOidcMappingsPost>[0]
        ),
      invalidate: () => invalidate(q.oidcMappings()),
    },
    options
  );

export const useUpdateOidcMapping = (
  options?: MutationOpts<OIDCClaimMappingRead, { mappingId: number; data: OIDCClaimMappingUpdate }>
) =>
  useApiMutation<OIDCClaimMappingRead, { mappingId: number; data: OIDCClaimMappingUpdate }>(
    {
      mutationFn: ({ mappingId, data }) =>
        updateOidcMappingApiV1SettingsOidcMappingsMappingIdPut(
          mappingId,
          data as Parameters<typeof updateOidcMappingApiV1SettingsOidcMappingsMappingIdPut>[1]
        ),
      invalidate: () => invalidate(q.oidcMappings()),
    },
    options
  );

export const useDeleteOidcMapping = (options?: MutationOpts<void, number>) =>
  useApiMutation<void, number>(
    {
      mutationFn: (mappingId) =>
        deleteOidcMappingApiV1SettingsOidcMappingsMappingIdDelete(mappingId),
      invalidate: () => invalidate(q.oidcMappings()),
    },
    options
  );

/** The deployment's own answer for one provider, for communities that have
 *  not made their own arrangement. Null where it has made none. */
export const useProviderDefault = (
  providerId: number | null,
  options?: QueryOpts<PlatformProviderDefaultRead | null>
) => {
  return useQuery<PlatformProviderDefaultRead | null>({
    queryKey: getGetProviderDefaultApiV1SettingsAuthProvidersProviderIdDefaultGetQueryKey(
      providerId as number
    ),
    queryFn: () =>
      getProviderDefaultApiV1SettingsAuthProvidersProviderIdDefaultGet(providerId as number),
    enabled: providerId !== null,
    ...options,
  });
};

const useInvalidateProviderDefault = (providerId: number) => {
  const queryClient = useQueryClient();
  return () => {
    void queryClient.invalidateQueries({
      queryKey:
        getGetProviderDefaultApiV1SettingsAuthProvidersProviderIdDefaultGetQueryKey(providerId),
    });
  };
};

export const useSetProviderDefault = (providerId: number) => {
  const invalidate = useInvalidateProviderDefault(providerId);
  return useMutation({
    mutationFn: (data: PlatformProviderDefaultUpdate) =>
      setProviderDefaultApiV1SettingsAuthProvidersProviderIdDefaultPut(providerId, data),
    onSuccess: invalidate,
  });
};

export const useClearProviderDefault = (providerId: number) => {
  const invalidate = useInvalidateProviderDefault(providerId);
  return useMutation({
    mutationFn: () =>
      clearProviderDefaultApiV1SettingsAuthProvidersProviderIdDefaultDelete(providerId),
    onSuccess: invalidate,
  });
};
