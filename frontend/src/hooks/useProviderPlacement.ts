import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import type {
  GuildNarrowingPending,
  PlacementCommunityRead,
  PlacementInitiativeRead,
  ProviderPlacementResponse,
  ProviderPlacementRuleCreate,
  ProviderPlacementRuleUpdate,
} from "@/api/generated/initiativeAPI.schemas";
import {
  createProviderPlacementRuleApiV1SettingsPlacementRulesPost,
  deleteProviderPlacementRuleApiV1SettingsPlacementRulesRuleIdDelete,
  getListPlacementCommunitiesApiV1SettingsPlacementCommunitiesGetQueryKey,
  getListPlacementRequestsApiV1SettingsPlacementRequestsGetQueryKey,
  getListPlacementTargetsApiV1SettingsPlacementProvidersProviderIdCommunitiesGuildIdInitiativesGetQueryKey,
  getListProviderPlacementApiV1SettingsPlacementGetQueryKey,
  listPlacementCommunitiesApiV1SettingsPlacementCommunitiesGet,
  listPlacementRequestsApiV1SettingsPlacementRequestsGet,
  listPlacementTargetsApiV1SettingsPlacementProvidersProviderIdCommunitiesGuildIdInitiativesGet,
  listProviderPlacementApiV1SettingsPlacementGet,
  setProviderPlacementEverywhereApiV1SettingsPlacementEverywherePut,
  updateProviderPlacementRuleApiV1SettingsPlacementRulesRuleIdPatch,
} from "@/api/generated/provider-placement/provider-placement";
import {
  agreeGuildNarrowingApiV1SettingsGuildsGuildIdNarrowingsConnectionIdPut,
  getReadGuildNarrowingsApiV1SettingsGuildsGuildIdNarrowingsGetQueryKey,
} from "@/api/generated/settings/settings";
import type { QueryOpts } from "@/types/query";

/** Every provider, the placement rules written on it, and whether they apply
 *  to every community. */
export const useProviderPlacement = (options?: QueryOpts<ProviderPlacementResponse>) => {
  return useQuery<ProviderPlacementResponse>({
    queryKey: getListProviderPlacementApiV1SettingsPlacementGetQueryKey(),
    queryFn: () => listProviderPlacementApiV1SettingsPlacementGet(),
    ...options,
  });
};

/** Communities a rule for this provider may name, searched by name. */
export const usePlacementCommunities = (
  providerId: number,
  query: string,
  options?: QueryOpts<PlacementCommunityRead[]>
) => {
  const params = { provider_id: providerId, q: query.trim() || undefined };
  return useQuery<PlacementCommunityRead[]>({
    queryKey: getListPlacementCommunitiesApiV1SettingsPlacementCommunitiesGetQueryKey(params),
    queryFn: () => listPlacementCommunitiesApiV1SettingsPlacementCommunitiesGet(params),
    ...options,
  });
};

/** The initiatives, and their roles, a rule naming this community may place
 *  people in. */
export const usePlacementTargets = (
  providerId: number,
  guildId: number | null,
  options?: QueryOpts<PlacementInitiativeRead[]>
) => {
  return useQuery<PlacementInitiativeRead[]>({
    queryKey:
      getListPlacementTargetsApiV1SettingsPlacementProvidersProviderIdCommunitiesGuildIdInitiativesGetQueryKey(
        providerId,
        guildId ?? 0
      ),
    queryFn: () =>
      listPlacementTargetsApiV1SettingsPlacementProvidersProviderIdCommunitiesGuildIdInitiativesGet(
        providerId,
        guildId ?? 0
      ),
    enabled: guildId !== null,
    // A community this provider's rules do not reach answers 404; asking
    // again would not change that.
    retry: false,
    ...options,
  });
};

const useInvalidatePlacement = () => {
  const queryClient = useQueryClient();
  return () => {
    void queryClient.invalidateQueries({
      queryKey: getListProviderPlacementApiV1SettingsPlacementGetQueryKey(),
    });
  };
};

/** Apply the rules to every community they name, or only where accepted. */
export const useSetPlacementEverywhere = () => {
  const invalidate = useInvalidatePlacement();
  return useMutation({
    mutationFn: (enabled: boolean) =>
      setProviderPlacementEverywhereApiV1SettingsPlacementEverywherePut({ enabled }),
    onSuccess: invalidate,
  });
};

export const useCreatePlacementRule = () => {
  const invalidate = useInvalidatePlacement();
  return useMutation({
    mutationFn: (data: ProviderPlacementRuleCreate) =>
      createProviderPlacementRuleApiV1SettingsPlacementRulesPost(data),
    onSuccess: invalidate,
  });
};

export const useUpdatePlacementRule = () => {
  const invalidate = useInvalidatePlacement();
  return useMutation({
    mutationFn: ({ ruleId, data }: { ruleId: number; data: ProviderPlacementRuleUpdate }) =>
      updateProviderPlacementRuleApiV1SettingsPlacementRulesRuleIdPatch(ruleId, data),
    onSuccess: invalidate,
  });
};

export const useDeletePlacementRule = () => {
  const invalidate = useInvalidatePlacement();
  return useMutation({
    mutationFn: (ruleId: number) =>
      deleteProviderPlacementRuleApiV1SettingsPlacementRulesRuleIdDelete(ruleId),
    onSuccess: invalidate,
  });
};

/** Every community whose claim to a domain or tenant is waiting for an answer. */
export const usePlacementRequests = (options?: QueryOpts<GuildNarrowingPending[]>) => {
  return useQuery<GuildNarrowingPending[]>({
    queryKey: getListPlacementRequestsApiV1SettingsPlacementRequestsGetQueryKey(),
    queryFn: () => listPlacementRequestsApiV1SettingsPlacementRequestsGet(),
    ...options,
  });
};

/** Agree that a community's claim is its own, from the list of those waiting. */
export const useAgreePlacementRequest = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ guildId, connectionId }: { guildId: number; connectionId: number }) =>
      agreeGuildNarrowingApiV1SettingsGuildsGuildIdNarrowingsConnectionIdPut(
        guildId,
        connectionId,
        { agreed: true }
      ),
    onSuccess: (_data, { guildId }) => {
      void queryClient.invalidateQueries({
        queryKey: getListPlacementRequestsApiV1SettingsPlacementRequestsGetQueryKey(),
      });
      void queryClient.invalidateQueries({
        queryKey: getReadGuildNarrowingsApiV1SettingsGuildsGuildIdNarrowingsGetQueryKey(guildId),
      });
    },
  });
};
