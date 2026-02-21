import { useMutation, useQuery, type UseQueryOptions } from "@tanstack/react-query";

import {
  getOidcSettingsApiV1SettingsAuthGet,
  getGetOidcSettingsApiV1SettingsAuthGetQueryKey,
  updateOidcSettingsApiV1SettingsAuthPut,
  getOidcMappingsApiV1SettingsOidcMappingsGet,
  getGetOidcMappingsApiV1SettingsOidcMappingsGetQueryKey,
  getOidcMappingOptionsApiV1SettingsOidcMappingsOptionsGet,
  getGetOidcMappingOptionsApiV1SettingsOidcMappingsOptionsGetQueryKey,
  updateOidcClaimPathApiV1SettingsOidcMappingsClaimPathPut,
  createOidcMappingApiV1SettingsOidcMappingsPost,
  updateOidcMappingApiV1SettingsOidcMappingsMappingIdPut,
  deleteOidcMappingApiV1SettingsOidcMappingsMappingIdDelete,
  getEmailSettingsApiV1SettingsEmailGet,
  getGetEmailSettingsApiV1SettingsEmailGetQueryKey,
  updateEmailSettingsApiV1SettingsEmailPut,
  sendTestEmailApiV1SettingsEmailTestPost,
  getInterfaceSettingsApiV1SettingsInterfaceGet,
  getGetInterfaceSettingsApiV1SettingsInterfaceGetQueryKey,
  updateInterfaceSettingsApiV1SettingsInterfacePut,
  getFcmConfigApiV1SettingsFcmConfigGet,
  getGetFcmConfigApiV1SettingsFcmConfigGetQueryKey,
} from "@/api/generated/settings/settings";
import {
  getChangelogApiV1ChangelogGet,
  getGetChangelogApiV1ChangelogGetQueryKey,
} from "@/api/generated/version/version";
import {
  invalidateAuthSettings,
  invalidateEmailSettings,
  invalidateInterfaceSettings,
  invalidateOidcMappings,
} from "@/api/query-keys";
import type {
  OIDCSettingsResponse,
  OIDCSettingsUpdate,
  OIDCMappingsResponse,
  OIDCClaimMappingCreate,
  OIDCClaimMappingRead,
  OIDCClaimMappingUpdate,
  OIDCClaimPathUpdate,
  EmailSettingsResponse,
  EmailSettingsUpdate,
  InterfaceSettingsResponse,
  InterfaceSettingsUpdate,
  FCMConfigResponse,
  GetChangelogApiV1ChangelogGetParams,
} from "@/api/generated/initiativeAPI.schemas";
import type { MutationOpts } from "@/types/mutation";

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

type QueryOpts<T> = Omit<UseQueryOptions<T>, "queryKey" | "queryFn">;

// ── Queries ─────────────────────────────────────────────────────────────────

export const useOidcSettings = (options?: QueryOpts<OIDCSettingsResponse>) => {
  return useQuery<OIDCSettingsResponse>({
    queryKey: getGetOidcSettingsApiV1SettingsAuthGetQueryKey(),
    queryFn: () =>
      getOidcSettingsApiV1SettingsAuthGet() as unknown as Promise<OIDCSettingsResponse>,
    ...options,
  });
};

export const useOidcMappings = () => {
  return useQuery<OIDCMappingsResponse>({
    queryKey: getGetOidcMappingsApiV1SettingsOidcMappingsGetQueryKey(),
    queryFn: () =>
      getOidcMappingsApiV1SettingsOidcMappingsGet() as unknown as Promise<OIDCMappingsResponse>,
  });
};

export const useOidcMappingOptions = () => {
  return useQuery<MappingOptions>({
    queryKey: getGetOidcMappingOptionsApiV1SettingsOidcMappingsOptionsGetQueryKey(),
    queryFn: () =>
      getOidcMappingOptionsApiV1SettingsOidcMappingsOptionsGet() as unknown as Promise<MappingOptions>,
  });
};

export const useEmailSettings = (options?: QueryOpts<EmailSettingsResponse>) => {
  return useQuery<EmailSettingsResponse>({
    queryKey: getGetEmailSettingsApiV1SettingsEmailGetQueryKey(),
    queryFn: () =>
      getEmailSettingsApiV1SettingsEmailGet() as unknown as Promise<EmailSettingsResponse>,
    ...options,
  });
};

export const useInterfaceSettings = (options?: QueryOpts<InterfaceSettingsResponse>) => {
  return useQuery<InterfaceSettingsResponse>({
    queryKey: getGetInterfaceSettingsApiV1SettingsInterfaceGetQueryKey(),
    queryFn: () =>
      getInterfaceSettingsApiV1SettingsInterfaceGet() as unknown as Promise<InterfaceSettingsResponse>,
    ...options,
  });
};

export const useFcmConfig = () => {
  return useQuery<FCMConfigResponse>({
    queryKey: getGetFcmConfigApiV1SettingsFcmConfigGetQueryKey(),
    queryFn: () => getFcmConfigApiV1SettingsFcmConfigGet() as unknown as Promise<FCMConfigResponse>,
    staleTime: 5 * 60 * 1000,
  });
};

export const useChangelog = (
  params: GetChangelogApiV1ChangelogGetParams,
  options?: QueryOpts<{ entries: ChangelogEntry[] }>
) => {
  return useQuery<{ entries: ChangelogEntry[] }>({
    queryKey: getGetChangelogApiV1ChangelogGetQueryKey(params),
    queryFn: () =>
      getChangelogApiV1ChangelogGet(params) as unknown as Promise<{
        entries: ChangelogEntry[];
      }>,
    ...options,
  });
};

// ── Settings Mutations ──────────────────────────────────────────────────────

export const useUpdateOidcSettings = (
  options?: MutationOpts<OIDCSettingsResponse, OIDCSettingsUpdate>
) => {
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async (data: OIDCSettingsUpdate) => {
      return updateOidcSettingsApiV1SettingsAuthPut(
        data as Parameters<typeof updateOidcSettingsApiV1SettingsAuthPut>[0]
      ) as unknown as Promise<OIDCSettingsResponse>;
    },
    onSuccess: (...args) => {
      void invalidateAuthSettings();
      onSuccess?.(...args);
    },
    onError,
    onSettled,
  });
};

export const useUpdateInterfaceSettings = (
  options?: MutationOpts<InterfaceSettingsResponse, InterfaceSettingsUpdate>
) => {
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async (data: InterfaceSettingsUpdate) => {
      return updateInterfaceSettingsApiV1SettingsInterfacePut(
        data as Parameters<typeof updateInterfaceSettingsApiV1SettingsInterfacePut>[0]
      ) as unknown as Promise<InterfaceSettingsResponse>;
    },
    onSuccess: (...args) => {
      void invalidateInterfaceSettings();
      onSuccess?.(...args);
    },
    onError,
    onSettled,
  });
};

export const useUpdateEmailSettings = (
  options?: MutationOpts<EmailSettingsResponse, EmailSettingsUpdate>
) => {
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async (data: EmailSettingsUpdate) => {
      return updateEmailSettingsApiV1SettingsEmailPut(
        data as Parameters<typeof updateEmailSettingsApiV1SettingsEmailPut>[0]
      ) as unknown as Promise<EmailSettingsResponse>;
    },
    onSuccess: (...args) => {
      void invalidateEmailSettings();
      onSuccess?.(...args);
    },
    onError,
    onSettled,
  });
};

export const useSendTestEmail = (
  options?: MutationOpts<void, Parameters<typeof sendTestEmailApiV1SettingsEmailTestPost>[0]>
) => {
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async (data: Parameters<typeof sendTestEmailApiV1SettingsEmailTestPost>[0]) => {
      await sendTestEmailApiV1SettingsEmailTestPost(data);
    },
    onSuccess,
    onError,
    onSettled,
  });
};

// ── OIDC Claim Mapping Mutations ────────────────────────────────────────────

export const useUpdateOidcClaimPath = (options?: MutationOpts<void, OIDCClaimPathUpdate>) => {
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async (data: OIDCClaimPathUpdate) => {
      await updateOidcClaimPathApiV1SettingsOidcMappingsClaimPathPut(data);
    },
    onSuccess: (...args) => {
      void invalidateOidcMappings();
      onSuccess?.(...args);
    },
    onError,
    onSettled,
  });
};

export const useCreateOidcMapping = (
  options?: MutationOpts<OIDCClaimMappingRead, OIDCClaimMappingCreate>
) => {
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async (data: OIDCClaimMappingCreate) => {
      return createOidcMappingApiV1SettingsOidcMappingsPost(
        data as Parameters<typeof createOidcMappingApiV1SettingsOidcMappingsPost>[0]
      ) as unknown as Promise<OIDCClaimMappingRead>;
    },
    onSuccess: (...args) => {
      void invalidateOidcMappings();
      onSuccess?.(...args);
    },
    onError,
    onSettled,
  });
};

export const useUpdateOidcMapping = (
  options?: MutationOpts<OIDCClaimMappingRead, { mappingId: number; data: OIDCClaimMappingUpdate }>
) => {
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async ({
      mappingId,
      data,
    }: {
      mappingId: number;
      data: OIDCClaimMappingUpdate;
    }) => {
      return updateOidcMappingApiV1SettingsOidcMappingsMappingIdPut(
        mappingId,
        data as Parameters<typeof updateOidcMappingApiV1SettingsOidcMappingsMappingIdPut>[1]
      ) as unknown as Promise<OIDCClaimMappingRead>;
    },
    onSuccess: (...args) => {
      void invalidateOidcMappings();
      onSuccess?.(...args);
    },
    onError,
    onSettled,
  });
};

export const useDeleteOidcMapping = (options?: MutationOpts<void, number>) => {
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async (mappingId: number) => {
      await deleteOidcMappingApiV1SettingsOidcMappingsMappingIdDelete(mappingId);
    },
    onSuccess: (...args) => {
      void invalidateOidcMappings();
      onSuccess?.(...args);
    },
    onError,
    onSettled,
  });
};
