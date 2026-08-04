import { useQuery } from "@tanstack/react-query";

import {
  getListDeviceTokensApiV1AuthDeviceTokensGetQueryKey,
  listDeviceTokensApiV1AuthDeviceTokensGet,
  revokeDeviceTokenApiV1AuthDeviceTokensTokenIdDelete,
} from "@/api/generated/auth/auth";
import type {
  ApiKeyCreateResponse,
  ApiKeyListResponse,
  DeviceTokenInfo,
} from "@/api/generated/initiativeAPI.schemas";
import {
  createMyApiKeyApiV1UsersMeApiKeysPost,
  deleteMyApiKeyApiV1UsersMeApiKeysApiKeyIdDelete,
  getListMyApiKeysApiV1UsersMeApiKeysGetQueryKey,
  listMyApiKeysApiV1UsersMeApiKeysGet,
} from "@/api/generated/users/users";
import { useApiMutation } from "@/hooks/useApiMutation";
import { queryClient } from "@/lib/queryClient";
import type { MutationOpts } from "@/types/mutation";

// ── Query Keys ──────────────────────────────────────────────────────────────

export const API_KEYS_QUERY_KEY = getListMyApiKeysApiV1UsersMeApiKeysGetQueryKey();
export const DEVICE_TOKENS_QUERY_KEY = getListDeviceTokensApiV1AuthDeviceTokensGetQueryKey();

// ── Queries ─────────────────────────────────────────────────────────────────

export const useMyApiKeys = () => {
  return useQuery<ApiKeyListResponse>({
    queryKey: API_KEYS_QUERY_KEY,
    queryFn: () => listMyApiKeysApiV1UsersMeApiKeysGet(),
  });
};

export const useDeviceTokens = () => {
  return useQuery<DeviceTokenInfo[]>({
    queryKey: DEVICE_TOKENS_QUERY_KEY,
    queryFn: () => listDeviceTokensApiV1AuthDeviceTokensGet(),
  });
};

// ── Mutations ───────────────────────────────────────────────────────────────

type CreateApiKeyVars = {
  name: string;
  expires_at?: string | null;
  read_only?: boolean;
  guild_id?: number | null;
};

export const useCreateApiKey = (options?: MutationOpts<ApiKeyCreateResponse, CreateApiKeyVars>) =>
  useApiMutation<ApiKeyCreateResponse, CreateApiKeyVars>(
    {
      mutationFn: (data) =>
        createMyApiKeyApiV1UsersMeApiKeysPost(
          data as Parameters<typeof createMyApiKeyApiV1UsersMeApiKeysPost>[0]
        ),
      invalidate: () => queryClient.invalidateQueries({ queryKey: API_KEYS_QUERY_KEY }),
    },
    options
  );

export const useDeleteApiKey = (options?: MutationOpts<void, number>) =>
  useApiMutation<void, number>(
    {
      mutationFn: (apiKeyId) => deleteMyApiKeyApiV1UsersMeApiKeysApiKeyIdDelete(apiKeyId),
      invalidate: () => queryClient.invalidateQueries({ queryKey: API_KEYS_QUERY_KEY }),
    },
    options
  );

export const useRevokeDeviceToken = (options?: MutationOpts<void, number>) =>
  useApiMutation<void, number>(
    {
      mutationFn: (tokenId) => revokeDeviceTokenApiV1AuthDeviceTokensTokenIdDelete(tokenId),
      invalidate: () => queryClient.invalidateQueries({ queryKey: DEVICE_TOKENS_QUERY_KEY }),
    },
    options
  );
