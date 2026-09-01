import { keepPreviousData, useQuery } from "@tanstack/react-query";

import type {
  SearchGuildApiV1GGuildIdSearchGetParams,
  SearchResults,
  SearchSuggestion,
  SuggestGuildApiV1GGuildIdSearchSuggestGetParams,
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

/** What a caller narrows a lookup to, beyond the words themselves. */
export type SuggestFilters = Omit<SuggestGuildApiV1GGuildIdSearchSuggestGetParams, "q">;

/**
 * Titles to jump to. Matches a partial last word, so it answers while the
 * reader is still typing.
 *
 * This is the ONE lookup behind every picker in the app — the command palette,
 * a mention, a wikilink, a queue link, a template. They differ only in what
 * they narrow to: `types` for what kind of thing, `initiative_id` for where,
 * and `template` for whether it is a blueprint. A picker built on this gets
 * ranking, prefix matching and every access gate without asking for them.
 */
export const useGuildSearchSuggest = (
  query: string,
  options?: QueryOpts<SearchSuggestion[]> & SuggestFilters
) => {
  const guildId = useActiveGuildId();
  const { limit, types, initiative_id, template, ...queryOptions } = options ?? {};
  const params: SuggestGuildApiV1GGuildIdSearchSuggestGetParams = {
    q: query,
    ...(limit != null ? { limit } : {}),
    ...(types ? { types } : {}),
    ...(initiative_id != null ? { initiative_id } : {}),
    ...(template != null ? { template } : {}),
  };
  return useQuery<SearchSuggestion[]>({
    queryKey: getSuggestGuildApiV1GGuildIdSearchSuggestGetQueryKey(guildId, params),
    queryFn: () => suggestGuildApiV1GGuildIdSearchSuggestGet(guildId, params),
    placeholderData: keepPreviousData,
    ...queryOptions,
  });
};
