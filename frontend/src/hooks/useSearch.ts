import { keepPreviousData, useQuery } from "@tanstack/react-query";

import type {
  SearchGuildApiV1GGuildIdSearchGetParams,
  SearchResults,
  SearchSuggestion,
} from "@/api/generated/initiativeAPI.schemas";
import {
  getSearchGuildApiV1GGuildIdSearchGetQueryKey,
  getSuggestGuildApiV1GGuildIdSearchSuggestGetQueryKey,
  searchGuildApiV1GGuildIdSearchGet,
  suggestGuildApiV1GGuildIdSearchSuggestGet,
} from "@/api/generated/search/search";
import { useActiveGuildId } from "@/hooks/useActiveGuildId";
import type { QueryOpts } from "@/types/query";

/**
 * Ranked matches across everything in the active guild.
 *
 * `keepPreviousData` is what makes the results page usable while typing: the
 * previous answer stays on screen instead of the list emptying between
 * keystrokes.
 */
export const useGuildSearch = (
  params: SearchGuildApiV1GGuildIdSearchGetParams,
  options?: QueryOpts<SearchResults>
) => {
  const guildId = useActiveGuildId();
  return useQuery<SearchResults>({
    queryKey: getSearchGuildApiV1GGuildIdSearchGetQueryKey(guildId, params),
    queryFn: () => searchGuildApiV1GGuildIdSearchGet(guildId, params),
    placeholderData: keepPreviousData,
    ...options,
  });
};

/**
 * Titles to jump to, for the command palette. Matches a partial last word, so
 * it answers while the reader is still typing.
 */
export const useGuildSearchSuggest = (
  query: string,
  options?: QueryOpts<SearchSuggestion[]> & { limit?: number }
) => {
  const guildId = useActiveGuildId();
  const { limit, ...queryOptions } = options ?? {};
  const params = { q: query, ...(limit != null ? { limit } : {}) };
  return useQuery<SearchSuggestion[]>({
    queryKey: getSuggestGuildApiV1GGuildIdSearchSuggestGetQueryKey(guildId, params),
    queryFn: () => suggestGuildApiV1GGuildIdSearchSuggestGet(guildId, params),
    placeholderData: keepPreviousData,
    ...queryOptions,
  });
};
