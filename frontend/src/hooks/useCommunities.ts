/**
 * The community directory.
 *
 * Platform-level, like the marketplace: one shared surface with no guild in the
 * request, so entries are keyed on what was asked for and nothing else. Joining
 * changes which guilds the caller belongs to, so the mutation refreshes the
 * guild switcher as well as the directory it was invoked from.
 */

import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  joinCommunityGuildApiV1GuildsCommunitiesGuildIdJoinPost,
  listCommunityGuildsApiV1GuildsCommunitiesGet,
} from "@/api/generated/guilds/guilds";
import type {
  CommunityGuildPage,
  GuildRead,
  ListCommunityGuildsApiV1GuildsCommunitiesGetParams,
} from "@/api/generated/initiativeAPI.schemas";
import type { QueryOpts } from "@/types/query";

/** Shared prefix, so joining can invalidate every filter combination at once
 *  (a card that was `already_member: false` no longer is, on any page). */
export const COMMUNITIES_QUERY_KEY = ["communities"] as const;

const communitiesQueryKey = (params: ListCommunityGuildsApiV1GuildsCommunitiesGetParams) =>
  [...COMMUNITIES_QUERY_KEY, params] as const;

/** The directory turns over when a guild opts in or out, not while someone
 *  scrolls it. */
const DIRECTORY_STALE_MS = 60 * 1000;

export const useCommunityGuilds = (
  params: ListCommunityGuildsApiV1GuildsCommunitiesGetParams,
  options?: QueryOpts<CommunityGuildPage>
) =>
  useQuery<CommunityGuildPage>({
    queryKey: communitiesQueryKey(params),
    queryFn: ({ signal }) =>
      listCommunityGuildsApiV1GuildsCommunitiesGet(params, undefined, signal),
    // Keeps the grid on screen while the next search or category loads, rather
    // than blanking it out on every keystroke.
    placeholderData: keepPreviousData,
    staleTime: DIRECTORY_STALE_MS,
    ...options,
  });

export const useJoinCommunityGuild = () => {
  const queryClient = useQueryClient();
  return useMutation<GuildRead, unknown, number>({
    mutationFn: (guildId: number) =>
      joinCommunityGuildApiV1GuildsCommunitiesGuildIdJoinPost(guildId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: COMMUNITIES_QUERY_KEY });
    },
  });
};
