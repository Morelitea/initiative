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
import { useActiveGuildId } from "@/hooks/useActiveGuildId";
import { queryClient } from "@/lib/queryClient";
import type { MutationOpts } from "@/types/mutation";
import type { QueryOpts } from "@/types/query";

/** A connection mutation touched the active connection list — refresh both the
 * owning admin's list and every member surface that resolves through it. */
const invalidateConnectionSurfaces = (scope: ConnectionScope) =>
  Promise.all([
    scope === "platform"
      ? invalidate(q.platformAIConnections())
      : invalidate(q.guildAIConnections()),
    invalidate(q.memberAI()),
    invalidate(q.resolvedAISettings()),
  ]);

/**
 * A member-scoped change (key or preference) refreshes that guild's member view
 * plus the resolved config the "generate with AI" buttons read. Keyed on the
 * explicit guild rather than the tab's active guild: the personal "My AI keys"
 * view manages any guild the user belongs to, which may not be the active one.
 */
const invalidateMemberSurfaces = (guildId: number) =>
  Promise.all([
    queryClient.invalidateQueries({
      queryKey: getGetMemberAiQueryKey(guildId),
    }),
    queryClient.invalidateQueries({
      queryKey: getGetResolvedAiSettingsQueryKey(guildId),
    }),
    // The personal "My AI" page aggregates every guild, so a per-guild write
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
      // resolved) across the active guild — flush the whole AI family.
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

// ── Guild connections (guild-scoped) ──────────────────────────────────────────

export const useGuildConnections = (options?: QueryOpts<AIConnectionResponse[]>) => {
  const guildId = useActiveGuildId();
  const { enabled: userEnabled = true, ...rest } = options ?? {};
  return useQuery<AIConnectionResponse[]>({
    queryKey: getListCommunityConnectionsQueryKey(guildId),
    queryFn: () => listCommunityConnections(guildId),
    enabled: userEnabled && guildId > 0,
    ...rest,
  });
};

export const useCreateGuildConnection = (
  options?: MutationOpts<AIConnectionResponse, AIConnectionCreate>
) => {
  const guildId = useActiveGuildId();
  const { onSuccess, ...rest } = options ?? {};
  return useMutation({
    ...rest,
    mutationFn: (data: AIConnectionCreate) => createCommunityConnection(guildId, data),
    onSuccess: (...args) => {
      void invalidateConnectionSurfaces("guild");
      onSuccess?.(...args);
    },
  });
};

export const useUpdateGuildConnection = (
  options?: MutationOpts<AIConnectionResponse, { connectionId: number; data: AIConnectionUpdate }>
) => {
  const guildId = useActiveGuildId();
  const { onSuccess, ...rest } = options ?? {};
  return useMutation({
    ...rest,
    mutationFn: ({ connectionId, data }: { connectionId: number; data: AIConnectionUpdate }) =>
      updateCommunityConnection(guildId, connectionId, data),
    onSuccess: (...args) => {
      void invalidateConnectionSurfaces("guild");
      onSuccess?.(...args);
    },
  });
};

export const useDeleteGuildConnection = (options?: MutationOpts<void, number>) => {
  const guildId = useActiveGuildId();
  const { onSuccess, ...rest } = options ?? {};
  return useMutation({
    ...rest,
    mutationFn: (connectionId: number) => deleteCommunityConnection(guildId, connectionId),
    onSuccess: (...args) => {
      void invalidateConnectionSurfaces("guild");
      onSuccess?.(...args);
    },
  });
};

export const useTestGuildConnection = (
  options?: MutationOpts<AIConnectionTestResponse, number>
) => {
  const guildId = useActiveGuildId();
  return useMutation({
    ...options,
    mutationFn: (connectionId: number) => testCommunityConnection(guildId, connectionId),
  });
};

export const useFetchGuildConnectionModels = (options?: MutationOpts<AIModelsResponse, number>) => {
  const guildId = useActiveGuildId();
  return useMutation({
    ...options,
    mutationFn: (connectionId: number) => fetchCommunityConnectionModels(guildId, connectionId),
  });
};

// ── My AI (cross-guild personal aggregate) ────────────────────────────────────

/**
 * Flat list of every AI connection available to the current user across all
 * their guilds (`GET /me/ai`) — one server-side aggregate, no per-guild fan-out.
 * Powers the personal "My AI" page; writes still go through the guild-scoped
 * member hooks below, keyed by each row's `guild_id`.
 */
export const useMyAI = (options?: QueryOpts<MyAIConnectionRow[]>) => {
  return useQuery<MyAIConnectionRow[]>({
    queryKey: getListMyAiQueryKey(),
    queryFn: () => listMyAi(),
    ...options,
  });
};

// ── Member view + preferences (guild-scoped) ──────────────────────────────────
//
// These take an explicit `guildId` rather than reading the tab's active guild:
// the personal "My AI keys" view lives outside the `/c/{id}` route tree and
// manages whichever guild the user picks, which need not be the active one.

export const useMemberAI = (guildId: number, options?: QueryOpts<MemberAIView>) => {
  const { enabled: userEnabled = true, ...rest } = options ?? {};
  return useQuery<MemberAIView>({
    queryKey: getGetMemberAiQueryKey(guildId),
    queryFn: () => getMemberAi(guildId),
    enabled: userEnabled && guildId > 0,
    ...rest,
  });
};

export const useSetMemberKey = (
  guildId: number,
  options?: MutationOpts<MemberAIView, MemberAIKeyUpdate>
) => {
  const { onSuccess, ...rest } = options ?? {};
  return useMutation({
    ...rest,
    mutationFn: (data: MemberAIKeyUpdate) => setMemberKey(guildId, data),
    onSuccess: (...args) => {
      void invalidateMemberSurfaces(guildId);
      onSuccess?.(...args);
    },
  });
};

export const useDeleteMemberKey = (
  guildId: number,
  options?: MutationOpts<MemberAIView, { scope: ConnectionScope; connectionId: number }>
) => {
  const { onSuccess, ...rest } = options ?? {};
  return useMutation({
    ...rest,
    mutationFn: ({ scope, connectionId }: { scope: ConnectionScope; connectionId: number }) =>
      deleteMemberKey(guildId, scope, connectionId),
    onSuccess: (...args) => {
      void invalidateMemberSurfaces(guildId);
      onSuccess?.(...args);
    },
  });
};

export const useSetMemberPref = (
  guildId: number,
  options?: MutationOpts<MemberAIView, MemberAIPrefUpdate>
) => {
  const { onSuccess, ...rest } = options ?? {};
  return useMutation({
    ...rest,
    mutationFn: (data: MemberAIPrefUpdate) => setMemberPref(guildId, data),
    onSuccess: (...args) => {
      void invalidateMemberSurfaces(guildId);
      onSuccess?.(...args);
    },
  });
};

export const useTestMemberAI = (
  guildId: number,
  options?: MutationOpts<AIConnectionTestResponse, void>
) => {
  return useMutation({
    ...options,
    mutationFn: () => testMemberAi(guildId),
  });
};
