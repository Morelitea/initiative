import { useQuery } from "@tanstack/react-query";

import {
  getListMySessionsApiV1AuthSessionsGetQueryKey,
  listMySessionsApiV1AuthSessionsGet,
  revokeMyOtherSessionsApiV1AuthSessionsRevokeOthersPost,
  revokeMySessionApiV1AuthSessionsSessionIdDelete,
} from "@/api/generated/auth/auth";
import { removeDeviceApiV1MeDmDevicesDeviceIdDelete } from "@/api/generated/direct-messages/direct-messages";
import type {
  ApiKeyCreateResponse,
  ApiKeyListResponse,
  SignedInSessionInfo,
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
export const SESSIONS_QUERY_KEY = getListMySessionsApiV1AuthSessionsGetQueryKey();

// ── Queries ─────────────────────────────────────────────────────────────────

export const useMyApiKeys = () => {
  return useQuery<ApiKeyListResponse>({
    queryKey: API_KEYS_QUERY_KEY,
    queryFn: () => listMyApiKeysApiV1UsersMeApiKeysGet(),
  });
};

export const useMySessions = () => {
  return useQuery<SignedInSessionInfo[]>({
    queryKey: SESSIONS_QUERY_KEY,
    queryFn: () => listMySessionsApiV1AuthSessionsGet(),
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

/** End one row of the list: its sign-in, or a message device with none. */
export const useEndSignedIn = (options?: MutationOpts<void, SignedInSessionInfo>) =>
  useApiMutation<void, SignedInSessionInfo>(
    {
      mutationFn: (row) =>
        row.id
          ? revokeMySessionApiV1AuthSessionsSessionIdDelete(row.id)
          : removeDeviceApiV1MeDmDevicesDeviceIdDelete(row.message_device_id as string),
      invalidate: () => queryClient.invalidateQueries({ queryKey: SESSIONS_QUERY_KEY }),
    },
    options
  );

export const useRevokeOtherSessions = (options?: MutationOpts<void, void>) =>
  useApiMutation<void, void>(
    {
      mutationFn: () => revokeMyOtherSessionsApiV1AuthSessionsRevokeOthersPost(),
      invalidate: () => queryClient.invalidateQueries({ queryKey: SESSIONS_QUERY_KEY }),
    },
    options
  );
