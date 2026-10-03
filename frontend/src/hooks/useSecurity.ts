import { useQuery } from "@tanstack/react-query";

import {
  getListMySessionsApiV1AuthSessionsGetQueryKey,
  listMySessionsApiV1AuthSessionsGet,
  revokeMyOtherSessionsApiV1AuthSessionsRevokeOthersPost,
  revokeMySessionApiV1AuthSessionsSessionIdDelete,
} from "@/api/generated/auth/auth";
import type {
  ApiKeyCreateResponse,
  ApiKeyListResponse,
  SignedInSessionInfo,
} from "@/api/generated/initiativeAPI.schemas";
import {
  createMyApiKeyApiV1MeApiKeysPost,
  deleteMyApiKeyApiV1MeApiKeysApiKeyIdDelete,
  getListMyApiKeysApiV1MeApiKeysGetQueryKey,
  listMyApiKeysApiV1MeApiKeysGet,
} from "@/api/generated/users/users";
import { useApiMutation } from "@/hooks/useApiMutation";
import { queryClient } from "@/lib/queryClient";
import type { MutationOpts } from "@/types/mutation";

// ── Query Keys ──────────────────────────────────────────────────────────────

export const API_KEYS_QUERY_KEY = getListMyApiKeysApiV1MeApiKeysGetQueryKey();
export const SESSIONS_QUERY_KEY = getListMySessionsApiV1AuthSessionsGetQueryKey();

// ── Queries ─────────────────────────────────────────────────────────────────

export const useMyApiKeys = () => {
  return useQuery<ApiKeyListResponse>({
    queryKey: API_KEYS_QUERY_KEY,
    queryFn: () => listMyApiKeysApiV1MeApiKeysGet(),
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
        createMyApiKeyApiV1MeApiKeysPost(
          data as Parameters<typeof createMyApiKeyApiV1MeApiKeysPost>[0]
        ),
      invalidate: () => queryClient.invalidateQueries({ queryKey: API_KEYS_QUERY_KEY }),
    },
    options
  );

export const useDeleteApiKey = (options?: MutationOpts<void, number>) =>
  useApiMutation<void, number>(
    {
      mutationFn: (apiKeyId) => deleteMyApiKeyApiV1MeApiKeysApiKeyIdDelete(apiKeyId),
      invalidate: () => queryClient.invalidateQueries({ queryKey: API_KEYS_QUERY_KEY }),
    },
    options
  );

export const useRevokeSession = (options?: MutationOpts<void, string>) =>
  useApiMutation<void, string>(
    {
      mutationFn: (sessionId) => revokeMySessionApiV1AuthSessionsSessionIdDelete(sessionId),
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
