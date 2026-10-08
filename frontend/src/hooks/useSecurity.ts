import { useQuery } from "@tanstack/react-query";

import {
  getListMySessionsQueryKey,
  listMySessions,
  revokeMyOtherSessions,
  revokeMySession,
} from "@/api/generated/auth/auth";
import { removeDevice } from "@/api/generated/direct-messages/direct-messages";
import type {
  ApiKeyCreateRequest,
  ApiKeyCreateResponse,
  ApiKeyListResponse,
  SignedInSessionInfo,
} from "@/api/generated/initiativeAPI.schemas";
import {
  createMyApiKey,
  deleteMyApiKey,
  getListMyApiKeysQueryKey,
  listMyApiKeys,
} from "@/api/generated/users/users";
import { useApiMutation } from "@/hooks/useApiMutation";
import { queryClient } from "@/lib/queryClient";
import type { MutationOpts } from "@/types/mutation";

// ── Query Keys ──────────────────────────────────────────────────────────────

export const API_KEYS_QUERY_KEY = getListMyApiKeysQueryKey();
export const SESSIONS_QUERY_KEY = getListMySessionsQueryKey();

// ── Queries ─────────────────────────────────────────────────────────────────

export const useMyApiKeys = () => {
  return useQuery<ApiKeyListResponse>({
    queryKey: API_KEYS_QUERY_KEY,
    queryFn: () => listMyApiKeys(),
  });
};

export const useMySessions = () => {
  return useQuery<SignedInSessionInfo[]>({
    queryKey: SESSIONS_QUERY_KEY,
    queryFn: () => listMySessions(),
  });
};

// ── Mutations ───────────────────────────────────────────────────────────────

export const useCreateApiKey = (
  options?: MutationOpts<ApiKeyCreateResponse, ApiKeyCreateRequest>
) =>
  useApiMutation<ApiKeyCreateResponse, ApiKeyCreateRequest>(
    {
      mutationFn: (data) => createMyApiKey(data),
      invalidate: () => queryClient.invalidateQueries({ queryKey: API_KEYS_QUERY_KEY }),
    },
    options
  );

export const useDeleteApiKey = (options?: MutationOpts<void, number>) =>
  useApiMutation<void, number>(
    {
      mutationFn: (apiKeyId) => deleteMyApiKey(apiKeyId),
      invalidate: () => queryClient.invalidateQueries({ queryKey: API_KEYS_QUERY_KEY }),
    },
    options
  );

/** End one row of the list: its sign-in, or a message device with none. */
export const useEndSignedIn = (options?: MutationOpts<void, SignedInSessionInfo>) =>
  useApiMutation<void, SignedInSessionInfo>(
    {
      mutationFn: (row) =>
        row.id ? revokeMySession(row.id) : removeDevice(row.message_device_id as string),
      invalidate: () => queryClient.invalidateQueries({ queryKey: SESSIONS_QUERY_KEY }),
    },
    options
  );

export const useRevokeOtherSessions = (options?: MutationOpts<void, void>) =>
  useApiMutation<void, void>(
    {
      mutationFn: () => revokeMyOtherSessions(),
      invalidate: () => queryClient.invalidateQueries({ queryKey: SESSIONS_QUERY_KEY }),
    },
    options
  );
