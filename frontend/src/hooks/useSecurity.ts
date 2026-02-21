import { useMutation, useQuery } from "@tanstack/react-query";

import {
  listMyApiKeysApiV1UsersMeApiKeysGet,
  getListMyApiKeysApiV1UsersMeApiKeysGetQueryKey,
  createMyApiKeyApiV1UsersMeApiKeysPost,
  deleteMyApiKeyApiV1UsersMeApiKeysApiKeyIdDelete,
} from "@/api/generated/users/users";
import {
  listDeviceTokensApiV1AuthDeviceTokensGet,
  getListDeviceTokensApiV1AuthDeviceTokensGetQueryKey,
  revokeDeviceTokenApiV1AuthDeviceTokensTokenIdDelete,
} from "@/api/generated/auth/auth";
import { queryClient } from "@/lib/queryClient";
import type { MutationOpts } from "@/types/mutation";
import type {
  ApiKeyCreateResponse,
  ApiKeyListResponse,
  DeviceTokenInfo,
} from "@/api/generated/initiativeAPI.schemas";

// ── Query Keys ──────────────────────────────────────────────────────────────

export const API_KEYS_QUERY_KEY = getListMyApiKeysApiV1UsersMeApiKeysGetQueryKey();
export const DEVICE_TOKENS_QUERY_KEY = getListDeviceTokensApiV1AuthDeviceTokensGetQueryKey();

// ── Queries ─────────────────────────────────────────────────────────────────

export const useMyApiKeys = () => {
  return useQuery<ApiKeyListResponse>({
    queryKey: API_KEYS_QUERY_KEY,
    queryFn: () => listMyApiKeysApiV1UsersMeApiKeysGet() as unknown as Promise<ApiKeyListResponse>,
  });
};

export const useDeviceTokens = () => {
  return useQuery<DeviceTokenInfo[]>({
    queryKey: DEVICE_TOKENS_QUERY_KEY,
    queryFn: () =>
      listDeviceTokensApiV1AuthDeviceTokensGet() as unknown as Promise<DeviceTokenInfo[]>,
  });
};

// ── Mutations ───────────────────────────────────────────────────────────────

type CreateApiKeyVars = { name: string; expires_at?: string | null };

export const useCreateApiKey = (options?: MutationOpts<ApiKeyCreateResponse, CreateApiKeyVars>) => {
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async (data: CreateApiKeyVars) => {
      return createMyApiKeyApiV1UsersMeApiKeysPost(
        data as Parameters<typeof createMyApiKeyApiV1UsersMeApiKeysPost>[0]
      ) as unknown as Promise<ApiKeyCreateResponse>;
    },
    onSuccess: (...args) => {
      void queryClient.invalidateQueries({ queryKey: API_KEYS_QUERY_KEY });
      onSuccess?.(...args);
    },
    onError: (...args) => {
      onError?.(...args);
    },
    onSettled,
  });
};

export const useDeleteApiKey = (options?: MutationOpts<void, number>) => {
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async (apiKeyId: number) => {
      await deleteMyApiKeyApiV1UsersMeApiKeysApiKeyIdDelete(apiKeyId);
    },
    onSuccess: (...args) => {
      void queryClient.invalidateQueries({ queryKey: API_KEYS_QUERY_KEY });
      onSuccess?.(...args);
    },
    onError: (...args) => {
      onError?.(...args);
    },
    onSettled,
  });
};

export const useRevokeDeviceToken = (options?: MutationOpts<void, number>) => {
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async (tokenId: number) => {
      await revokeDeviceTokenApiV1AuthDeviceTokensTokenIdDelete(tokenId);
    },
    onSuccess: (...args) => {
      void queryClient.invalidateQueries({ queryKey: DEVICE_TOKENS_QUERY_KEY });
      onSuccess?.(...args);
    },
    onError: (...args) => {
      onError?.(...args);
    },
    onSettled,
  });
};
