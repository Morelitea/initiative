import { useMutation, useQuery } from "@tanstack/react-query";

import {
  createCommunityConnection,
  createPlatformConnection,
  deleteCommunityConnection,
  deleteMemberKey,
  deletePlatformConnection,
  fetchCommunityConnectionModels,
  fetchPlatformConnectionModels,
  getGetMemberAiQueryKey,
  getGetPlatformAiModeQueryKey,
  getGetResolvedAiSettingsQueryKey,
  getListCommunityConnectionsQueryKey,
  getListMyAiQueryKey,
  getListPlatformConnectionsQueryKey,
  getMemberAi,
  getPlatformAiMode,
  listCommunityConnections,
  listMyAi,
  listPlatformConnections,
  setMemberKey,
  setMemberPref,
  testCommunityConnection,
  testMemberAi,
  testPlatformConnection,
  updateCommunityConnection,
  updatePlatformAiMode,
  updatePlatformConnection,
} from "@/api/generated/ai-settings/ai-settings";
import type {
  AIConnectionCreate,
  AIConnectionResponse,
  AIConnectionTestResponse,
  AIConnectionUpdate,
  AIModelsResponse,
  ConnectionScope,
  MemberAIKeyUpdate,
  MemberAIPrefUpdate,
  MemberAIView,
  MyAIConnectionRow,
  PlatformAIModeResponse,
  PlatformAIModeUpdate,
} from "@/api/generated/initiativeAPI.schemas";
import { invalidate, q } from "@/api/query-keys";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { queryClient } from "@/lib/queryClient";
import type { MutationOpts } from "@/types/mutation";
import type { QueryOpts } from "@/types/query";

/** A connection mutation touched the active connection list — refresh both the
 * owning admin's list and every member surface that resolves through it. */
const invalidateConnectionSurfaces = (scope: ConnectionScope) =>
  Promise.all([
    scope === "platform"
      ? invalidate(q.platformAIConnections())
      : invalidate(q.communityAIConnections()),
    invalidate(q.memberAI()),
    invalidate(q.resolvedAISettings()),
  ]);

/**
 * A member-scoped change (key or preference) refreshes that community's member view
 * plus the resolved config the "generate with AI" buttons read. Keyed on the
 * explicit community rather than the tab's active community: the personal "My AI keys"
 * view manages any community the user belongs to, which may not be the active one.
 */
const invalidateMemberSurfaces = (communityId: number) =>
  Promise.all([
    queryClient.invalidateQueries({
      queryKey: getGetMemberAiQueryKey(communityId),
    }),
    queryClient.invalidateQueries({
      queryKey: getGetResolvedAiSettingsQueryKey(communityId),
    }),
    // The personal "My AI" page aggregates every community, so a per-community write
    // must refresh it too.
    invalidate(q.myAI()),
  ]);

// ── Platform mode (personal / platform) ───────────────────────────────────────

export const usePlatformAIMode = (options?: QueryOpts<PlatformAIModeResponse>) => {
  return useQuery<PlatformAIModeResponse>({
    queryKey: getGetPlatformAiModeQueryKey(),
    queryFn: () => getPlatformAiMode(),
    ...options,
  });
};

export const useUpdatePlatformAIMode = (
  options?: MutationOpts<PlatformAIModeResponse, PlatformAIModeUpdate>
) => {
  const { onSuccess, ...rest } = options ?? {};
  return useMutation({
    ...rest,
    mutationFn: (data: PlatformAIModeUpdate) => updatePlatformAiMode(data),
    onSuccess: (...args) => {
      // A mode change flips every downstream surface (connections, member view,
      // resolved) across the active community — flush the whole AI family.
      void invalidate(q.allAISettings());
      onSuccess?.(...args);
    },
  });
};

// ── Platform connections (personal / platform) ────────────────────────────────

export const usePlatformConnections = (options?: QueryOpts<AIConnectionResponse[]>) => {
  return useQuery<AIConnectionResponse[]>({
    queryKey: getListPlatformConnectionsQueryKey(),
    queryFn: () => listPlatformConnections(),
    ...options,
  });
};

export const useCreatePlatformConnection = (
  options?: MutationOpts<AIConnectionResponse, AIConnectionCreate>
) => {
  const { onSuccess, ...rest } = options ?? {};
  return useMutation({
    ...rest,
    mutationFn: (data: AIConnectionCreate) => createPlatformConnection(data),
    onSuccess: (...args) => {
      void invalidateConnectionSurfaces("platform");
      onSuccess?.(...args);
    },
  });
};

export const useUpdatePlatformConnection = (
  options?: MutationOpts<AIConnectionResponse, { connectionId: number; data: AIConnectionUpdate }>
) => {
  const { onSuccess, ...rest } = options ?? {};
  return useMutation({
    ...rest,
    mutationFn: ({ connectionId, data }: { connectionId: number; data: AIConnectionUpdate }) =>
      updatePlatformConnection(connectionId, data),
    onSuccess: (...args) => {
      void invalidateConnectionSurfaces("platform");
      onSuccess?.(...args);
    },
  });
};

export const useDeletePlatformConnection = (options?: MutationOpts<void, number>) => {
  const { onSuccess, ...rest } = options ?? {};
  return useMutation({
    ...rest,
    mutationFn: (connectionId: number) => deletePlatformConnection(connectionId),
    onSuccess: (...args) => {
      void invalidateConnectionSurfaces("platform");
      onSuccess?.(...args);
    },
  });
};

export const useTestPlatformConnection = (
  options?: MutationOpts<AIConnectionTestResponse, number>
) => {
  return useMutation({
    ...options,
    mutationFn: (connectionId: number) => testPlatformConnection(connectionId),
  });
};

export const useFetchPlatformConnectionModels = (
  options?: MutationOpts<AIModelsResponse, number>
) => {
  return useMutation({
    ...options,
    mutationFn: (connectionId: number) => fetchPlatformConnectionModels(connectionId),
  });
};

// ── Community connections (community-scoped) ──────────────────────────────────────────

export const useCommunityConnections = (options?: QueryOpts<AIConnectionResponse[]>) => {
  const communityId = useActiveCommunityId();
  const { enabled: userEnabled = true, ...rest } = options ?? {};
  return useQuery<AIConnectionResponse[]>({
    queryKey: getListCommunityConnectionsQueryKey(communityId),
    queryFn: () => listCommunityConnections(communityId),
    enabled: userEnabled && communityId > 0,
    ...rest,
  });
};

export const useCreateCommunityConnection = (
  options?: MutationOpts<AIConnectionResponse, AIConnectionCreate>
) => {
  const communityId = useActiveCommunityId();
  const { onSuccess, ...rest } = options ?? {};
  return useMutation({
    ...rest,
    mutationFn: (data: AIConnectionCreate) => createCommunityConnection(communityId, data),
    onSuccess: (...args) => {
      void invalidateConnectionSurfaces("community");
      onSuccess?.(...args);
    },
  });
};

export const useUpdateCommunityConnection = (
  options?: MutationOpts<AIConnectionResponse, { connectionId: number; data: AIConnectionUpdate }>
) => {
  const communityId = useActiveCommunityId();
  const { onSuccess, ...rest } = options ?? {};
  return useMutation({
    ...rest,
    mutationFn: ({ connectionId, data }: { connectionId: number; data: AIConnectionUpdate }) =>
      updateCommunityConnection(communityId, connectionId, data),
    onSuccess: (...args) => {
      void invalidateConnectionSurfaces("community");
      onSuccess?.(...args);
    },
  });
};

export const useDeleteCommunityConnection = (options?: MutationOpts<void, number>) => {
  const communityId = useActiveCommunityId();
  const { onSuccess, ...rest } = options ?? {};
  return useMutation({
    ...rest,
    mutationFn: (connectionId: number) => deleteCommunityConnection(communityId, connectionId),
    onSuccess: (...args) => {
      void invalidateConnectionSurfaces("community");
      onSuccess?.(...args);
    },
  });
};

export const useTestCommunityConnection = (
  options?: MutationOpts<AIConnectionTestResponse, number>
) => {
  const communityId = useActiveCommunityId();
  return useMutation({
    ...options,
    mutationFn: (connectionId: number) => testCommunityConnection(communityId, connectionId),
  });
};

export const useFetchCommunityConnectionModels = (
  options?: MutationOpts<AIModelsResponse, number>
) => {
  const communityId = useActiveCommunityId();
  return useMutation({
    ...options,
    mutationFn: (connectionId: number) => fetchCommunityConnectionModels(communityId, connectionId),
  });
};

// ── My AI (cross-community personal aggregate) ────────────────────────────────────

/**
 * Flat list of every AI connection available to the current user across all
 * their communities (`GET /me/ai`) — one server-side aggregate, no per-community fan-out.
 * Powers the personal "My AI" page; writes still go through the community-scoped
 * member hooks below, keyed by each row's `community_id`.
 */
export const useMyAI = (options?: QueryOpts<MyAIConnectionRow[]>) => {
  return useQuery<MyAIConnectionRow[]>({
    queryKey: getListMyAiQueryKey(),
    queryFn: () => listMyAi(),
    ...options,
  });
};

// ── Member view + preferences (community-scoped) ──────────────────────────────────
//
// These take an explicit `communityId` rather than reading the tab's active community:
// the personal "My AI keys" view lives outside the `/c/{id}` route tree and
// manages whichever community the user picks, which need not be the active one.

export const useMemberAI = (communityId: number, options?: QueryOpts<MemberAIView>) => {
  const { enabled: userEnabled = true, ...rest } = options ?? {};
  return useQuery<MemberAIView>({
    queryKey: getGetMemberAiQueryKey(communityId),
    queryFn: () => getMemberAi(communityId),
    enabled: userEnabled && communityId > 0,
    ...rest,
  });
};

export const useSetMemberKey = (
  communityId: number,
  options?: MutationOpts<MemberAIView, MemberAIKeyUpdate>
) => {
  const { onSuccess, ...rest } = options ?? {};
  return useMutation({
    ...rest,
    mutationFn: (data: MemberAIKeyUpdate) => setMemberKey(communityId, data),
    onSuccess: (...args) => {
      void invalidateMemberSurfaces(communityId);
      onSuccess?.(...args);
    },
  });
};

export const useDeleteMemberKey = (
  communityId: number,
  options?: MutationOpts<MemberAIView, { scope: ConnectionScope; connectionId: number }>
) => {
  const { onSuccess, ...rest } = options ?? {};
  return useMutation({
    ...rest,
    mutationFn: ({ scope, connectionId }: { scope: ConnectionScope; connectionId: number }) =>
      deleteMemberKey(communityId, scope, connectionId),
    onSuccess: (...args) => {
      void invalidateMemberSurfaces(communityId);
      onSuccess?.(...args);
    },
  });
};

export const useSetMemberPref = (
  communityId: number,
  options?: MutationOpts<MemberAIView, MemberAIPrefUpdate>
) => {
  const { onSuccess, ...rest } = options ?? {};
  return useMutation({
    ...rest,
    mutationFn: (data: MemberAIPrefUpdate) => setMemberPref(communityId, data),
    onSuccess: (...args) => {
      void invalidateMemberSurfaces(communityId);
      onSuccess?.(...args);
    },
  });
};

export const useTestMemberAI = (
  communityId: number,
  options?: MutationOpts<AIConnectionTestResponse, void>
) => {
  return useMutation({
    ...options,
    mutationFn: () => testMemberAi(communityId),
  });
};
