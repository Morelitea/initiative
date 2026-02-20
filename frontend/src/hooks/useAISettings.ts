import { useQuery, type UseQueryOptions } from "@tanstack/react-query";

import {
  getPlatformAiSettingsApiV1SettingsAiPlatformGet,
  getGetPlatformAiSettingsApiV1SettingsAiPlatformGetQueryKey,
  getGuildAiSettingsApiV1SettingsAiGuildGet,
  getGetGuildAiSettingsApiV1SettingsAiGuildGetQueryKey,
  getUserAiSettingsApiV1SettingsAiUserGet,
  getGetUserAiSettingsApiV1SettingsAiUserGetQueryKey,
} from "@/api/generated/ai-settings/ai-settings";
import type {
  PlatformAISettingsResponse,
  GuildAISettingsResponse,
  UserAISettingsResponse,
} from "@/api/generated/initiativeAPI.schemas";

type QueryOpts<T> = Omit<UseQueryOptions<T>, "queryKey" | "queryFn">;

// ── Queries ─────────────────────────────────────────────────────────────────

export const usePlatformAISettings = (options?: QueryOpts<PlatformAISettingsResponse>) => {
  return useQuery<PlatformAISettingsResponse>({
    queryKey: getGetPlatformAiSettingsApiV1SettingsAiPlatformGetQueryKey(),
    queryFn: () =>
      getPlatformAiSettingsApiV1SettingsAiPlatformGet() as unknown as Promise<PlatformAISettingsResponse>,
    ...options,
  });
};

export const useGuildAISettings = (
  guildId: number | string | null | undefined,
  options?: QueryOpts<GuildAISettingsResponse>
) => {
  const { enabled: userEnabled = true, ...rest } = options ?? {};
  return useQuery<GuildAISettingsResponse>({
    queryKey: [...getGetGuildAiSettingsApiV1SettingsAiGuildGetQueryKey(), guildId],
    queryFn: () =>
      getGuildAiSettingsApiV1SettingsAiGuildGet() as unknown as Promise<GuildAISettingsResponse>,
    enabled: userEnabled && !!guildId,
    ...rest,
  });
};

export const useUserAISettings = () => {
  return useQuery<UserAISettingsResponse>({
    queryKey: getGetUserAiSettingsApiV1SettingsAiUserGetQueryKey(),
    queryFn: () =>
      getUserAiSettingsApiV1SettingsAiUserGet() as unknown as Promise<UserAISettingsResponse>,
  });
};
