import { useQuery } from "@tanstack/react-query";

import {
  listMyApiKeysApiV1UsersMeApiKeysGet,
  getListMyApiKeysApiV1UsersMeApiKeysGetQueryKey,
} from "@/api/generated/users/users";
import {
  listDeviceTokensApiV1AuthDeviceTokensGet,
  getListDeviceTokensApiV1AuthDeviceTokensGetQueryKey,
} from "@/api/generated/auth/auth";
import type { ApiKeyListResponse, DeviceTokenInfo } from "@/api/generated/initiativeAPI.schemas";

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
