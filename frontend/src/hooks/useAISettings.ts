import { useMutation, useQuery } from "@tanstack/react-query";

import {
  createGuildConnectionApiV1GGuildIdSettingsAiConnectionsPost,
  createPlatformConnectionApiV1SettingsAiPlatformConnectionsPost,
  deleteGuildConnectionApiV1GGuildIdSettingsAiConnectionsConnectionIdDelete,
  deleteMemberKeyApiV1GGuildIdSettingsAiMeKeyScopeConnectionIdDelete,
  deletePlatformConnectionApiV1SettingsAiPlatformConnectionsConnectionIdDelete,
  fetchGuildConnectionModelsApiV1GGuildIdSettingsAiConnectionsConnectionIdModelsPost,
  fetchPlatformConnectionModelsApiV1SettingsAiPlatformConnectionsConnectionIdModelsPost,
  getGetMemberAiApiV1GGuildIdSettingsAiMeGetQueryKey,
  getGetPlatformAiModeApiV1SettingsAiPlatformModeGetQueryKey,
  getGetResolvedAiSettingsApiV1GGuildIdSettingsAiResolvedGetQueryKey,
  getListGuildConnectionsApiV1GGuildIdSettingsAiConnectionsGetQueryKey,
  getListMyAiApiV1MeAiGetQueryKey,
  getListPlatformConnectionsApiV1SettingsAiPlatformConnectionsGetQueryKey,
  getMemberAiApiV1GGuildIdSettingsAiMeGet,
  getPlatformAiModeApiV1SettingsAiPlatformModeGet,
  listGuildConnectionsApiV1GGuildIdSettingsAiConnectionsGet,
  listMyAiApiV1MeAiGet,
  listPlatformConnectionsApiV1SettingsAiPlatformConnectionsGet,
  setMemberKeyApiV1GGuildIdSettingsAiMeKeyPut,
  setMemberPrefApiV1GGuildIdSettingsAiMePrefPut,
  testGuildConnectionApiV1GGuildIdSettingsAiConnectionsConnectionIdTestPost,
  testMemberAiApiV1GGuildIdSettingsAiMeTestPost,
  testPlatformConnectionApiV1SettingsAiPlatformConnectionsConnectionIdTestPost,
  updateGuildConnectionApiV1GGuildIdSettingsAiConnectionsConnectionIdPut,
  updatePlatformAiModeApiV1SettingsAiPlatformModePut,
  updatePlatformConnectionApiV1SettingsAiPlatformConnectionsConnectionIdPut,
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
import {
  invalidateAllAISettings,
  invalidateGuildAIConnections,
  invalidateMemberAI,
  invalidateMyAI,
  invalidatePlatformAIConnections,
  invalidateResolvedAISettings,
} from "@/api/query-keys";
import { useActiveGuildId } from "@/hooks/useActiveGuildId";
import { queryClient } from "@/lib/queryClient";
import type { MutationOpts } from "@/types/mutation";
import type { QueryOpts } from "@/types/query";

/** A connection mutation touched the active connection list — refresh both the
 * owning admin's list and every member surface that resolves through it. */
const invalidateConnectionSurfaces = (scope: ConnectionScope) =>
  Promise.all([
    scope === "platform" ? invalidatePlatformAIConnections() : invalidateGuildAIConnections(),
    invalidateMemberAI(),
    invalidateResolvedAISettings(),
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
      queryKey: getGetMemberAiApiV1GGuildIdSettingsAiMeGetQueryKey(guildId),
    }),
    queryClient.invalidateQueries({
      queryKey: getGetResolvedAiSettingsApiV1GGuildIdSettingsAiResolvedGetQueryKey(guildId),
    }),
    // The personal "My AI" page aggregates every guild, so a per-guild write
    // must refresh it too.
    invalidateMyAI(),
  ]);

// ── Platform mode (personal / platform) ───────────────────────────────────────

export const usePlatformAIMode = (options?: QueryOpts<PlatformAIModeResponse>) => {
  return useQuery<PlatformAIModeResponse>({
    queryKey: getGetPlatformAiModeApiV1SettingsAiPlatformModeGetQueryKey(),
    queryFn: () => getPlatformAiModeApiV1SettingsAiPlatformModeGet(),
    ...options,
  });
};

export const useUpdatePlatformAIMode = (
  options?: MutationOpts<PlatformAIModeResponse, PlatformAIModeUpdate>
) => {
  const { onSuccess, ...rest } = options ?? {};
  return useMutation({
    ...rest,
    mutationFn: (data: PlatformAIModeUpdate) =>
      updatePlatformAiModeApiV1SettingsAiPlatformModePut(data),
    onSuccess: (...args) => {
      // A mode change flips every downstream surface (connections, member view,
      // resolved) across the active guild — flush the whole AI family.
      void invalidateAllAISettings();
      onSuccess?.(...args);
    },
  });
};

// ── Platform connections (personal / platform) ────────────────────────────────

export const usePlatformConnections = (options?: QueryOpts<AIConnectionResponse[]>) => {
  return useQuery<AIConnectionResponse[]>({
    queryKey: getListPlatformConnectionsApiV1SettingsAiPlatformConnectionsGetQueryKey(),
    queryFn: () => listPlatformConnectionsApiV1SettingsAiPlatformConnectionsGet(),
    ...options,
  });
};

export const useCreatePlatformConnection = (
  options?: MutationOpts<AIConnectionResponse, AIConnectionCreate>
) => {
  const { onSuccess, ...rest } = options ?? {};
  return useMutation({
    ...rest,
    mutationFn: (data: AIConnectionCreate) =>
      createPlatformConnectionApiV1SettingsAiPlatformConnectionsPost(data),
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
      updatePlatformConnectionApiV1SettingsAiPlatformConnectionsConnectionIdPut(connectionId, data),
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
    mutationFn: (connectionId: number) =>
      deletePlatformConnectionApiV1SettingsAiPlatformConnectionsConnectionIdDelete(connectionId),
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
    mutationFn: (connectionId: number) =>
      testPlatformConnectionApiV1SettingsAiPlatformConnectionsConnectionIdTestPost(connectionId),
  });
};

export const useFetchPlatformConnectionModels = (
  options?: MutationOpts<AIModelsResponse, number>
) => {
  return useMutation({
    ...options,
    mutationFn: (connectionId: number) =>
      fetchPlatformConnectionModelsApiV1SettingsAiPlatformConnectionsConnectionIdModelsPost(
        connectionId
      ),
  });
};

// ── Guild connections (guild-scoped) ──────────────────────────────────────────

export const useGuildConnections = (options?: QueryOpts<AIConnectionResponse[]>) => {
  const guildId = useActiveGuildId();
  const { enabled: userEnabled = true, ...rest } = options ?? {};
  return useQuery<AIConnectionResponse[]>({
    queryKey: getListGuildConnectionsApiV1GGuildIdSettingsAiConnectionsGetQueryKey(guildId),
    queryFn: () => listGuildConnectionsApiV1GGuildIdSettingsAiConnectionsGet(guildId),
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
    mutationFn: (data: AIConnectionCreate) =>
      createGuildConnectionApiV1GGuildIdSettingsAiConnectionsPost(guildId, data),
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
      updateGuildConnectionApiV1GGuildIdSettingsAiConnectionsConnectionIdPut(
        guildId,
        connectionId,
        data
      ),
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
    mutationFn: (connectionId: number) =>
      deleteGuildConnectionApiV1GGuildIdSettingsAiConnectionsConnectionIdDelete(
        guildId,
        connectionId
      ),
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
    mutationFn: (connectionId: number) =>
      testGuildConnectionApiV1GGuildIdSettingsAiConnectionsConnectionIdTestPost(
        guildId,
        connectionId
      ),
  });
};

export const useFetchGuildConnectionModels = (options?: MutationOpts<AIModelsResponse, number>) => {
  const guildId = useActiveGuildId();
  return useMutation({
    ...options,
    mutationFn: (connectionId: number) =>
      fetchGuildConnectionModelsApiV1GGuildIdSettingsAiConnectionsConnectionIdModelsPost(
        guildId,
        connectionId
      ),
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
    queryKey: getListMyAiApiV1MeAiGetQueryKey(),
    queryFn: () => listMyAiApiV1MeAiGet(),
    ...options,
  });
};

// ── Member view + preferences (guild-scoped) ──────────────────────────────────
//
// These take an explicit `guildId` rather than reading the tab's active guild:
// the personal "My AI keys" view lives outside the `/g/{id}` route tree and
// manages whichever guild the user picks, which need not be the active one.

export const useMemberAI = (guildId: number, options?: QueryOpts<MemberAIView>) => {
  const { enabled: userEnabled = true, ...rest } = options ?? {};
  return useQuery<MemberAIView>({
    queryKey: getGetMemberAiApiV1GGuildIdSettingsAiMeGetQueryKey(guildId),
    queryFn: () => getMemberAiApiV1GGuildIdSettingsAiMeGet(guildId),
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
    mutationFn: (data: MemberAIKeyUpdate) =>
      setMemberKeyApiV1GGuildIdSettingsAiMeKeyPut(guildId, data),
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
      deleteMemberKeyApiV1GGuildIdSettingsAiMeKeyScopeConnectionIdDelete(
        guildId,
        scope,
        connectionId
      ),
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
    mutationFn: (data: MemberAIPrefUpdate) =>
      setMemberPrefApiV1GGuildIdSettingsAiMePrefPut(guildId, data),
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
    mutationFn: () => testMemberAiApiV1GGuildIdSettingsAiMeTestPost(guildId),
  });
};
