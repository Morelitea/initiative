import { useMutation, useQuery } from "@tanstack/react-query";

import {
  fetchAiModelsApiV1GGuildIdSettingsAiModelsPost,
  getGetGuildAiSettingsApiV1GGuildIdSettingsAiGuildGetQueryKey,
  getGetPlatformAiSettingsApiV1SettingsAiPlatformGetQueryKey,
  getGetUserAiSettingsApiV1GGuildIdSettingsAiUserGetQueryKey,
  getGuildAiSettingsApiV1GGuildIdSettingsAiGuildGet,
  getPlatformAiSettingsApiV1SettingsAiPlatformGet,
  getUserAiSettingsApiV1GGuildIdSettingsAiUserGet,
  testAiConnectionApiV1GGuildIdSettingsAiTestPost,
  updateGuildAiSettingsApiV1GGuildIdSettingsAiGuildPut,
  updatePlatformAiSettingsApiV1SettingsAiPlatformPut,
  updateUserAiSettingsApiV1GGuildIdSettingsAiUserPut,
} from "@/api/generated/ai-settings/ai-settings";
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
import {
  invalidateGuildAISettings,
  invalidatePlatformAISettings,
  invalidateResolvedAISettings,
  invalidateUserAISettings,
} from "@/api/query-keys";
import { useActiveGuildId } from "@/hooks/useActiveGuildId";
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
  const activeGuildId = useActiveGuildId();
  const { enabled: userEnabled = true, ...rest } = options ?? {};
  return useQuery<GuildAISettingsResponse>({
    queryKey: [
      ...getGetGuildAiSettingsApiV1GGuildIdSettingsAiGuildGetQueryKey(activeGuildId),
      guildId,
    ],
    queryFn: () =>
      getGuildAiSettingsApiV1GGuildIdSettingsAiGuildGet(
        activeGuildId
      ) as unknown as Promise<GuildAISettingsResponse>,
    enabled: userEnabled && !!guildId,
    ...rest,
  });
};

export const useUserAISettings = () => {
  const guildId = useActiveGuildId();
  return useQuery<UserAISettingsResponse>({
    queryKey: getGetUserAiSettingsApiV1GGuildIdSettingsAiUserGetQueryKey(guildId),
    queryFn: () =>
      getUserAiSettingsApiV1GGuildIdSettingsAiUserGet(
        guildId
      ) as unknown as Promise<UserAISettingsResponse>,
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
  const guildId = useActiveGuildId();
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async (data: GuildAISettingsUpdate) => {
      return updateGuildAiSettingsApiV1GGuildIdSettingsAiGuildPut(
        guildId,
        data as Parameters<typeof updateGuildAiSettingsApiV1GGuildIdSettingsAiGuildPut>[1]
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
  const guildId = useActiveGuildId();
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async (data: UserAISettingsUpdate) => {
      return updateUserAiSettingsApiV1GGuildIdSettingsAiUserPut(
        guildId,
        data as Parameters<typeof updateUserAiSettingsApiV1GGuildIdSettingsAiUserPut>[1]
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
  const guildId = useActiveGuildId();
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async (data: AITestConnectionRequest) => {
      return testAiConnectionApiV1GGuildIdSettingsAiTestPost(
        guildId,
        data as Parameters<typeof testAiConnectionApiV1GGuildIdSettingsAiTestPost>[1]
      ) as unknown as Promise<AITestConnectionResponse>;
    },
    onSuccess,
    onError,
    onSettled,
  });
};

export const useFetchAIModels = (options?: MutationOpts<AIModelsResponse, AIModelsRequest>) => {
  const guildId = useActiveGuildId();
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async (data: AIModelsRequest) => {
      return fetchAiModelsApiV1GGuildIdSettingsAiModelsPost(
        guildId,
        data as Parameters<typeof fetchAiModelsApiV1GGuildIdSettingsAiModelsPost>[1]
      ) as unknown as Promise<AIModelsResponse>;
    },
    onSuccess,
    onError,
    onSettled,
  });
};
