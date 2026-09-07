/**
 * Who there is to reach, and the one write that stars them.
 *
 * The rosters are a single server-side aggregate — the backend walks the
 * reader's communities the way every other "my" page does — and the starred
 * list is a second read, because a favorite may be somebody you share no
 * community with. Growing one community past its first page is a third: a
 * request for that community alone.
 *
 * These were My Contacts' reads; the page is gone and the new-conversation
 * picker on My Messages makes them now.
 */

import { useInfiniteQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback } from "react";

import {
  getListContactSectionsApiV1MeContactsGetQueryKey,
  getListFavoriteContactsApiV1MeContactsFavoritesGetQueryKey,
  listContactSectionsApiV1MeContactsGet,
  useAddFavoriteContactApiV1MeContactsFavoritesUserIdPut,
  useListContactSectionsApiV1MeContactsGet,
  useListFavoriteContactsApiV1MeContactsFavoritesGet,
  useRemoveFavoriteContactApiV1MeContactsFavoritesUserIdDelete,
} from "@/api/generated/contacts/contacts";

/** Members read per community at a time. */
const CONTACTS_PAGE_SIZE = 20;

/** How long a page of a community stays fresh enough to reuse. */
const PAGE_STALE_MS = 30_000;

const sectionParams = (search: string) =>
  search.trim() ? { search, page_size: CONTACTS_PAGE_SIZE } : { page_size: CONTACTS_PAGE_SIZE };

const favoriteParams = (search: string) => (search.trim() ? { search } : undefined);

/** One community, one page — the request a roster makes for itself. */
const guildPageParams = (guildId: number, page: number, search: string) => ({
  guild_ids: [guildId],
  page,
  page_size: CONTACTS_PAGE_SIZE,
  ...(search.trim() ? { search } : {}),
});

/**
 * Every community's first page, under one term.
 *
 * ``enabled`` is for a surface that is not on screen yet — a dialog behind a
 * button — where the aggregate is a whole walk of the reader's communities and
 * there is no reason to walk it until somebody opens the thing.
 */
export const useContactSections = (search: string, options?: { enabled?: boolean }) =>
  useListContactSectionsApiV1MeContactsGet(sectionParams(search), {
    query: { enabled: options?.enabled ?? true },
  });

/** The reader's starred people. `enabled` for the same reason as above. */
export const useFavoriteContacts = (search: string, options?: { enabled?: boolean }) =>
  useListFavoriteContactsApiV1MeContactsFavoritesGet(favoriteParams(search), {
    query: { enabled: options?.enabled ?? true },
  });

/**
 * A page of one community beyond its first.
 *
 * The aggregate already carries page one of every section, so this only runs
 * once a reader pages a section forward. Each page is its own cache entry, so
 * stepping back to one already read is immediate.
 */

/**
 * Everybody else in one community, past the first page.
 *
 * For a surface that grows a list rather than paging it — a picker, where
 * stepping between pages loses the person somebody had just spotted. It starts
 * at page two because the aggregate already carries page one of every
 * community, and it does not run at all until the reader asks for more, so a
 * roster nobody reaches the bottom of costs nothing.
 */
export const useMoreCommunityContacts = (guildId: number, search: string, enabled: boolean) =>
  useInfiniteQuery({
    queryKey: ["contacts", "community", guildId, search.trim()] as const,
    queryFn: ({ pageParam }) =>
      listContactSectionsApiV1MeContactsGet(guildPageParams(guildId, pageParam, search)),
    initialPageParam: 2,
    // The section says whether there is one after it; the page number is how
    // many have been fetched, offset by the one that arrived with the walk.
    getNextPageParam: (last, all) => (last.sections?.[0]?.has_next ? all.length + 2 : undefined),
    enabled,
    staleTime: PAGE_STALE_MS,
  });

/**
 * Star or unstar somebody.
 *
 * Both lists are invalidated on either: the person moves into or out of
 * Favorites, and the star on their community rows has to follow.
 */
export const useToggleFavoriteContact = () => {
  const queryClient = useQueryClient();

  const invalidate = useCallback(() => {
    void queryClient.invalidateQueries({
      queryKey: getListFavoriteContactsApiV1MeContactsFavoritesGetQueryKey(),
    });
    void queryClient.invalidateQueries({
      queryKey: getListContactSectionsApiV1MeContactsGetQueryKey(),
    });
  }, [queryClient]);

  const add = useAddFavoriteContactApiV1MeContactsFavoritesUserIdPut({
    mutation: { onSuccess: invalidate },
  });
  const remove = useRemoveFavoriteContactApiV1MeContactsFavoritesUserIdDelete({
    mutation: { onSuccess: invalidate },
  });

  return useCallback(
    (userId: number, starred: boolean) => {
      if (starred) remove.mutate({ userId });
      else add.mutate({ userId });
    },
    [add, remove]
  );
};
