import { useQuery, type UseQueryOptions } from "@tanstack/react-query";

import {
  getOidcSettingsApiV1SettingsAuthGet,
  getGetOidcSettingsApiV1SettingsAuthGetQueryKey,
  getOidcMappingsApiV1SettingsOidcMappingsGet,
  getGetOidcMappingsApiV1SettingsOidcMappingsGetQueryKey,
  getOidcMappingOptionsApiV1SettingsOidcMappingsOptionsGet,
  getGetOidcMappingOptionsApiV1SettingsOidcMappingsOptionsGetQueryKey,
  getEmailSettingsApiV1SettingsEmailGet,
  getGetEmailSettingsApiV1SettingsEmailGetQueryKey,
  getInterfaceSettingsApiV1SettingsInterfaceGet,
  getGetInterfaceSettingsApiV1SettingsInterfaceGetQueryKey,
  getFcmConfigApiV1SettingsFcmConfigGet,
  getGetFcmConfigApiV1SettingsFcmConfigGetQueryKey,
} from "@/api/generated/settings/settings";
import {
  getChangelogApiV1ChangelogGet,
  getGetChangelogApiV1ChangelogGetQueryKey,
} from "@/api/generated/version/version";
import type {
  OIDCSettingsResponse,
  OIDCMappingsResponse,
  EmailSettingsResponse,
  InterfaceSettingsResponse,
  FCMConfigResponse,
  GetChangelogApiV1ChangelogGetParams,
} from "@/api/generated/initiativeAPI.schemas";

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
