import { useQuery } from "@tanstack/react-query";

import {
  createAuthProviderApiV1SettingsAuthProvidersPost,
  deleteAuthProviderApiV1SettingsAuthProvidersProviderIdDelete,
  getListAuthProvidersApiV1SettingsAuthProvidersGetQueryKey,
  listAuthProvidersApiV1SettingsAuthProvidersGet,
  updateAuthProviderApiV1SettingsAuthProvidersProviderIdPatch,
} from "@/api/generated/auth-providers/auth-providers";
import type {
  AuthProviderAdminRead,
  AuthProviderCreate,
  AuthProviderUpdate,
  EmailSettingsResponse,
  EmailSettingsUpdate,
  FCMConfigResponse,
  GetChangelogApiV1ChangelogGetParams,
  InterfaceSettingsResponse,
  InterfaceSettingsUpdate,
  OIDCClaimMappingCreate,
  OIDCClaimMappingRead,
  OIDCClaimMappingUpdate,
  OIDCClaimPathUpdate,
  OIDCMappingsResponse,
  OIDCSettingsResponse,
  OIDCSettingsUpdate,
  PlatformGuildStorageRead,
  PlatformGuildStorageUpdate,
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
  getGetStorageBackfillStatusApiV1SettingsStorageBackfillGetQueryKey,
  getGetStorageSettingsApiV1SettingsStorageGetQueryKey,
  getInterfaceSettingsApiV1SettingsInterfaceGet,
  getListPlatformGuildStorageApiV1SettingsGuildsGetQueryKey,
  getOidcMappingOptionsApiV1SettingsOidcMappingsOptionsGet,
  getOidcMappingsApiV1SettingsOidcMappingsGet,
  getOidcSettingsApiV1SettingsAuthGet,
  getStorageBackfillStatusApiV1SettingsStorageBackfillGet,
  getStorageSettingsApiV1SettingsStorageGet,
  listPlatformGuildStorageApiV1SettingsGuildsGet,
  sendTestEmailApiV1SettingsEmailTestPost,
  startStorageBackfillApiV1SettingsStorageBackfillPost,
  testStorageConnectionApiV1SettingsStorageTestPost,
  updateEmailSettingsApiV1SettingsEmailPut,
  updateInterfaceSettingsApiV1SettingsInterfacePut,
  updateOidcClaimPathApiV1SettingsOidcMappingsClaimPathPut,
  updateOidcMappingApiV1SettingsOidcMappingsMappingIdPut,
  updateOidcSettingsApiV1SettingsAuthPut,
  updatePlatformGuildStorageApiV1SettingsGuildsGuildIdPatch,
  updateStorageSettingsApiV1SettingsStoragePut,
} from "@/api/generated/settings/settings";
import {
  getChangelogApiV1ChangelogGet,
  getGetChangelogApiV1ChangelogGetQueryKey,
} from "@/api/generated/version/version";
import {
  invalidateAuthProviders,
  invalidateAuthSettings,
  invalidateEmailSettings,
  invalidateInterfaceSettings,
  invalidateOidcMappings,
  invalidatePlatformGuilds,
  invalidateStorageSettings,
} from "@/api/query-keys";
import { useApiMutation } from "@/hooks/useApiMutation";
import type { MutationOpts } from "@/types/mutation";
import type { QueryOpts } from "@/types/query";

// ── Local types for untyped or loosely-typed generated responses ─────────

/** Strongly-typed version of the mapping options response. */
export interface MappingOptionItem {
  id: number;
  name: string;
}

export interface MappingInitiativeOption extends MappingOptionItem {
  guild_id: number;
}

export interface MappingRoleOption extends MappingOptionItem {
  initiative_id: number;
  guild_id: number;
}

export interface MappingOptions {
  guilds: MappingOptionItem[];
  initiatives: MappingInitiativeOption[];
  initiative_roles: MappingRoleOption[];
}

/** Changelog entry shape returned by the backend. */
export interface ChangelogEntry {
  version: string;
  date: string;
  changes: string;
}

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
  return useQuery<MappingOptions>({
    queryKey: getGetOidcMappingOptionsApiV1SettingsOidcMappingsOptionsGetQueryKey(),
    // The backend endpoint has no typed response model (plain dict), so the
    // generated type is an index signature; the local MappingOptions interface
    // narrows it. Remove the cast once the backend declares a response schema.
    queryFn: () =>
      getOidcMappingOptionsApiV1SettingsOidcMappingsOptionsGet() as unknown as Promise<MappingOptions>,
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
  options?: QueryOpts<{ entries: ChangelogEntry[] }>
) => {
  return useQuery<{ entries: ChangelogEntry[] }>({
    queryKey: getGetChangelogApiV1ChangelogGetQueryKey(params),
    // The backend endpoint has no typed response model (plain dict); the local
    // ChangelogEntry shape narrows it. Remove the cast once the backend
    // declares a response schema.
    queryFn: () =>
      getChangelogApiV1ChangelogGet(params) as unknown as Promise<{ entries: ChangelogEntry[] }>,
    ...options,
  });
};

// ── Settings Mutations ──────────────────────────────────────────────────────

export const useUpdateOidcSettings = (
  options?: MutationOpts<OIDCSettingsResponse, OIDCSettingsUpdate>
) =>
  useApiMutation<OIDCSettingsResponse, OIDCSettingsUpdate>(
    {
      mutationFn: (data) =>
        updateOidcSettingsApiV1SettingsAuthPut(
          data as Parameters<typeof updateOidcSettingsApiV1SettingsAuthPut>[0]
        ),
      invalidate: () => invalidateAuthSettings(),
    },
    options
  );

export const useCreateAuthProvider = (
  options?: MutationOpts<AuthProviderAdminRead, AuthProviderCreate>
) =>
  useApiMutation<AuthProviderAdminRead, AuthProviderCreate>(
    {
      mutationFn: (data) => createAuthProviderApiV1SettingsAuthProvidersPost(data),
      invalidate: () => invalidateAuthProviders(),
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
      invalidate: () => invalidateAuthProviders(),
    },
    options
  );

export const useDeleteAuthProvider = (options?: MutationOpts<void, number>) =>
  useApiMutation<void, number>(
    {
      mutationFn: (providerId) =>
        deleteAuthProviderApiV1SettingsAuthProvidersProviderIdDelete(providerId),
      invalidate: () => invalidateAuthProviders(),
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
      invalidate: () => invalidateInterfaceSettings(),
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
      invalidate: () => invalidateEmailSettings(),
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
      invalidate: () => invalidateStorageSettings(),
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
      invalidate: () => invalidatePlatformGuilds(),
    },
    options
  );

// ── OIDC Claim Mapping Mutations ────────────────────────────────────────────

export const useUpdateOidcClaimPath = (options?: MutationOpts<void, OIDCClaimPathUpdate>) =>
  useApiMutation<void, OIDCClaimPathUpdate>(
    {
      mutationFn: async (data) => {
        await updateOidcClaimPathApiV1SettingsOidcMappingsClaimPathPut(data);
      },
      invalidate: () => invalidateOidcMappings(),
    },
    options
  );

export const useCreateOidcMapping = (
  options?: MutationOpts<OIDCClaimMappingRead, OIDCClaimMappingCreate>
) =>
  useApiMutation<OIDCClaimMappingRead, OIDCClaimMappingCreate>(
    {
      mutationFn: (data) =>
        createOidcMappingApiV1SettingsOidcMappingsPost(
          data as Parameters<typeof createOidcMappingApiV1SettingsOidcMappingsPost>[0]
        ),
      invalidate: () => invalidateOidcMappings(),
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
      invalidate: () => invalidateOidcMappings(),
    },
    options
  );

export const useDeleteOidcMapping = (options?: MutationOpts<void, number>) =>
  useApiMutation<void, number>(
    {
      mutationFn: (mappingId) =>
        deleteOidcMappingApiV1SettingsOidcMappingsMappingIdDelete(mappingId),
      invalidate: () => invalidateOidcMappings(),
    },
    options
  );
