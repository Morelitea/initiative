import { keepPreviousData, useQuery } from "@tanstack/react-query";

import type {
  SearchGuildApiV1GGuildIdSearchGetParams,
  SearchResults,
  SearchSuggestion,
  SuggestGuildApiV1GGuildIdSearchSuggestGetParams,
} from "@/api/generated/initiativeAPI.schemas";
import {
  getRecentGuildApiV1GGuildIdSearchRecentGetQueryKey,
  getSearchGuildApiV1GGuildIdSearchGetQueryKey,
  getSuggestGuildApiV1GGuildIdSearchSuggestGetQueryKey,
  recentGuildApiV1GGuildIdSearchRecentGet,
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
 *
 * It answers only the half of a picker's job that starts with typed words;
 * `useGuildPickerSuggestions` is what a picker asks, and calls this in turn.
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

/**
 * What a picker offers before anything has been typed.
 *
 * The most recently changed things the caller could name, narrowed the same way
 * the lookup is — so a picker's suggestions and its search are the same set of
 * things, and picking from the list can never offer what typing could not find.
 *
 * Not exported: a picker asks `useGuildPickerSuggestions`, which switches to
 * this on its own. Asking for recents directly is asking half a question.
 */
const useGuildRecentSuggestions = (options?: QueryOpts<SearchSuggestion[]> & SuggestFilters) => {
  const guildId = useActiveGuildId();
  const { limit, types, initiative_id, template, ...queryOptions } = options ?? {};
  const params = {
    ...(limit != null ? { limit } : {}),
    ...(types ? { types } : {}),
    ...(initiative_id != null ? { initiative_id } : {}),
    ...(template != null ? { template } : {}),
  };
  return useQuery<SearchSuggestion[]>({
    queryKey: getRecentGuildApiV1GGuildIdSearchRecentGetQueryKey(guildId, params),
    queryFn: () => recentGuildApiV1GGuildIdSearchRecentGet(guildId, params),
    ...queryOptions,
  });
};

// One stable empty answer, so a picker's own memos do not recompute on every
// render while a lookup is in flight.
const NOTHING: SearchSuggestion[] = [];

/** What a picker has to show, and what it is currently able to say about it. */
export interface PickerSuggestions {
  /** The rows to offer. */
  items: SearchSuggestion[];
  /** Whether these answer typed words, or are what was there to begin with. */
  searched: boolean;
  /**
   * True while what is on screen answers a query the reader has moved on from.
   * Shown, so the list does not blink shut between keystrokes — but not
   * offered to the keyboard, since it is not an answer to what is typed now.
   */
  stale: boolean;
  /** No answer yet. `isFetching` also covers refetching a list already shown. */
  isLoading: boolean;
  isFetching: boolean;
}

/**
 * Everything a picker shows, whichever of its two questions it is asking.
 *
 * A picker asks one question before anything is typed — "what could I point
 * at" — and another once something is: "which of them did I mean". The lookup
 * only answers the second, because it matches words and there are none yet, so
 * a picker built on it alone opens empty and teaches nothing: not what kind of
 * thing belongs here, not whether there is anything to point at at all.
 *
 * Both questions take the same narrowing and run under the same gates, so the
 * list a picker opens on can never hold something typing would refuse to find.
 */
export const useGuildPickerSuggestions = (
  query: string,
  options?: QueryOpts<SearchSuggestion[]> & SuggestFilters
): PickerSuggestions => {
  const { enabled = true, ...narrowing } = options ?? {};
  const searched = query.trim().length > 0;
  // Both are called every render and only one is switched on: a switched-off
  // query keeps the answer it was last given, which belongs to the other
  // question.
  const recents = useGuildRecentSuggestions({ ...narrowing, enabled: enabled && !searched });
  const matches = useGuildSearchSuggest(query, { ...narrowing, enabled: enabled && searched });
  const active = searched ? matches : recents;
  return {
    items: active.data ?? NOTHING,
    searched,
    stale: searched && matches.isPlaceholderData,
    isLoading: active.isLoading,
    isFetching: active.isFetching,
  };
};
