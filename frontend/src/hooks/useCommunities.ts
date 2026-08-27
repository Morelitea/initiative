/**
 * The community directory.
 *
 * Platform-level, like the marketplace: one shared surface with no guild in the
 * request, so entries are keyed on what was asked for and nothing else. Joining
 * changes which guilds the caller belongs to, so the mutation refreshes the
 * guild switcher as well as the directory it was invoked from.
 */

import {
  keepPreviousData,
  useInfiniteQuery,
  useMutation,
  useQueryClient,
} from "@tanstack/react-query";

import {
  joinCommunityGuildApiV1GuildsCommunitiesGuildIdJoinPost,
  listCommunityGuildsApiV1GuildsCommunitiesGet,
} from "@/api/generated/guilds/guilds";
import type {
  CommunityGuildPage,
  GuildRead,
  ListCommunityGuildsApiV1GuildsCommunitiesGetParams,
} from "@/api/generated/initiativeAPI.schemas";

/** Shared prefix, so joining can invalidate every filter combination at once
 *  (a card that was `already_member: false` no longer is, on any page). */
export const COMMUNITIES_QUERY_KEY = ["communities"] as const;

/** The directory turns over when a guild opts in or out, not while someone
 *  scrolls it. */
const DIRECTORY_STALE_MS = 60 * 1000;

/** Cards per request. The endpoint caps a page at 60, so "show more" fetches
 *  the next page rather than asking for a bigger one — a growing page_size
 *  runs into that ceiling and takes the whole grid down with it. */
export const COMMUNITIES_PAGE_SIZE = 24;

/** Everything except the page number, which the query owns. */
export type CommunityFilters = Omit<
  ListCommunityGuildsApiV1GuildsCommunitiesGetParams,
  "page" | "page_size"
>;

export const useCommunityGuilds = (filters: CommunityFilters) =>
  useInfiniteQuery<CommunityGuildPage>({
    queryKey: [...COMMUNITIES_QUERY_KEY, filters],
    queryFn: ({ pageParam, signal }) =>
      listCommunityGuildsApiV1GuildsCommunitiesGet(
        { ...filters, page: pageParam as number, page_size: COMMUNITIES_PAGE_SIZE },
        undefined,
        signal
      ),
    initialPageParam: 1,
    // ``total`` is how many matched, not how many were returned, so the page
    // after the last full one is the end.
    getNextPageParam: (lastPage, allPages) => {
      const loaded = allPages.reduce((count, page) => count + page.items.length, 0);
      return loaded < lastPage.total ? allPages.length + 1 : undefined;
    },
    // Keeps the grid on screen while the next search or category loads, rather
    // than blanking it out on every keystroke.
    placeholderData: keepPreviousData,
    staleTime: DIRECTORY_STALE_MS,
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
