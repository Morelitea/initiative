import { useMutation, useQuery } from "@tanstack/react-query";

import {
  getPlatformAiSettingsApiV1SettingsAiPlatformGet,
  getGetPlatformAiSettingsApiV1SettingsAiPlatformGetQueryKey,
  updatePlatformAiSettingsApiV1SettingsAiPlatformPut,
  getGuildAiSettingsApiV1SettingsAiGuildGet,
  getGetGuildAiSettingsApiV1SettingsAiGuildGetQueryKey,
  updateGuildAiSettingsApiV1SettingsAiGuildPut,
  getUserAiSettingsApiV1SettingsAiUserGet,
  getGetUserAiSettingsApiV1SettingsAiUserGetQueryKey,
  updateUserAiSettingsApiV1SettingsAiUserPut,
  testAiConnectionApiV1SettingsAiTestPost,
  fetchAiModelsApiV1SettingsAiModelsPost,
} from "@/api/generated/ai-settings/ai-settings";
import {
  invalidateGuildAISettings,
  invalidatePlatformAISettings,
  invalidateResolvedAISettings,
  invalidateUserAISettings,
} from "@/api/query-keys";
import type {
  AIModelsRequest,
  AIModelsResponse,
  AITestConnectionRequest,
  AITestConnectionResponse,
  GuildAISettingsResponse,
  GuildAISettingsUpdate,
  PlatformAISettingsResponse,
  PlatformAISettingsUpdate,
  UserAISettingsResponse,
  UserAISettingsUpdate,
} from "@/api/generated/initiativeAPI.schemas";
import type { MutationOpts } from "@/types/mutation";
import type { QueryOpts } from "@/types/query";

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

// ── Mutations ───────────────────────────────────────────────────────────────

export const useUpdatePlatformAISettings = (
  options?: MutationOpts<PlatformAISettingsResponse, PlatformAISettingsUpdate>
) => {
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async (data: PlatformAISettingsUpdate) => {
      return updatePlatformAiSettingsApiV1SettingsAiPlatformPut(
        data
      ) as unknown as Promise<PlatformAISettingsResponse>;
    },
    onSuccess: (...args) => {
      void invalidatePlatformAISettings();
      void invalidateResolvedAISettings();
      onSuccess?.(...args);
    },
    onError,
    onSettled,
  });
};

export const useUpdateGuildAISettings = (
  options?: MutationOpts<GuildAISettingsResponse, GuildAISettingsUpdate>
) => {
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async (data: GuildAISettingsUpdate) => {
      return updateGuildAiSettingsApiV1SettingsAiGuildPut(
        data as Parameters<typeof updateGuildAiSettingsApiV1SettingsAiGuildPut>[0]
      ) as unknown as Promise<GuildAISettingsResponse>;
    },
    onSuccess: (...args) => {
      void invalidateGuildAISettings();
      void invalidateResolvedAISettings();
      onSuccess?.(...args);
    },
    onError,
    onSettled,
  });
};

export const useUpdateUserAISettings = (
  options?: MutationOpts<UserAISettingsResponse, UserAISettingsUpdate>
) => {
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async (data: UserAISettingsUpdate) => {
      return updateUserAiSettingsApiV1SettingsAiUserPut(
        data as Parameters<typeof updateUserAiSettingsApiV1SettingsAiUserPut>[0]
      ) as unknown as Promise<UserAISettingsResponse>;
    },
    onSuccess: (...args) => {
      void invalidateUserAISettings();
      void invalidateResolvedAISettings();
      onSuccess?.(...args);
    },
    onError,
    onSettled,
  });
};

export const useTestAIConnection = (
  options?: MutationOpts<AITestConnectionResponse, AITestConnectionRequest>
) => {
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async (data: AITestConnectionRequest) => {
      return testAiConnectionApiV1SettingsAiTestPost(
        data as Parameters<typeof testAiConnectionApiV1SettingsAiTestPost>[0]
      ) as unknown as Promise<AITestConnectionResponse>;
    },
    onSuccess,
    onError,
    onSettled,
  });
};

export const useFetchAIModels = (options?: MutationOpts<AIModelsResponse, AIModelsRequest>) => {
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async (data: AIModelsRequest) => {
      return fetchAiModelsApiV1SettingsAiModelsPost(
        data as Parameters<typeof fetchAiModelsApiV1SettingsAiModelsPost>[0]
      ) as unknown as Promise<AIModelsResponse>;
    },
    onSuccess,
    onError,
    onSettled,
  });
};
