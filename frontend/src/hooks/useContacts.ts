/**
 * The reads and one write behind My Contacts.
 *
 * The sections are a single server-side aggregate — the backend walks the
 * reader's communities the way every other "my" page does — and the starred
 * list is a second read, because a favorite may be somebody you share no
 * community with. Paging one community deeper is a third: a request for that
 * community alone.
 */

import { useQueryClient } from "@tanstack/react-query";
import { useCallback } from "react";

import {
  getListContactSectionsApiV1MeContactsGetQueryKey,
  getListFavoriteContactsApiV1MeContactsFavoritesGetQueryKey,
  listContactSectionsApiV1MeContactsGet,
  listFavoriteContactsApiV1MeContactsFavoritesGet,
  useAddFavoriteContactApiV1MeContactsFavoritesUserIdPut,
  useListContactSectionsApiV1MeContactsGet,
  useListFavoriteContactsApiV1MeContactsFavoritesGet,
  useRemoveFavoriteContactApiV1MeContactsFavoritesUserIdDelete,
} from "@/api/generated/contacts/contacts";

/** Members shown per community at a time. */
export const CONTACTS_PAGE_SIZE = 20;

/** How long a page of a community stays fresh enough to reuse. */
const PAGE_STALE_MS = 30_000;

const sectionParams = (search: string) =>
  search.trim() ? { search, page_size: CONTACTS_PAGE_SIZE } : { page_size: CONTACTS_PAGE_SIZE };

const favoriteParams = (search: string) => (search.trim() ? { search } : undefined);

/** One community, one page — the request a section makes for itself. */
const guildPageParams = (guildId: number, page: number, search: string) => ({
  guild_ids: [guildId],
  page,
  page_size: CONTACTS_PAGE_SIZE,
  ...(search.trim() ? { search } : {}),
});

/** Query keys and params the route loader prefetches under. */
export const contactsPrefetch = (search: string) => ({
  sections: {
    params: sectionParams(search),
    queryKey: getListContactSectionsApiV1MeContactsGetQueryKey(sectionParams(search)),
    queryFn: () => listContactSectionsApiV1MeContactsGet(sectionParams(search)),
  },
  favorites: {
    params: favoriteParams(search),
    queryKey: getListFavoriteContactsApiV1MeContactsFavoritesGetQueryKey(favoriteParams(search)),
    queryFn: () => listFavoriteContactsApiV1MeContactsFavoritesGet(favoriteParams(search)),
  },
});

export const useContactSections = (search: string) =>
  useListContactSectionsApiV1MeContactsGet(sectionParams(search));

export const useFavoriteContacts = (search: string) =>
  useListFavoriteContactsApiV1MeContactsFavoritesGet(favoriteParams(search));

/**
 * A page of one community beyond its first.
 *
 * The aggregate already carries page one of every section, so this only runs
 * once a reader pages a section forward. Each page is its own cache entry, so
 * stepping back to one already read is immediate.
 */
export const useContactSectionPage = (guildId: number, page: number, search: string) =>
  useListContactSectionsApiV1MeContactsGet(guildPageParams(guildId, page, search), {
    query: { enabled: page > 1, staleTime: PAGE_STALE_MS },
  });

/** Warm the page a pager button would land on, before it is clicked. */
export const usePrefetchContactSectionPage = () => {
  const queryClient = useQueryClient();

  return useCallback(
    (guildId: number, page: number, search: string) => {
      if (page <= 1) return;
      const params = guildPageParams(guildId, page, search);
      void queryClient.prefetchQuery({
        queryKey: getListContactSectionsApiV1MeContactsGetQueryKey(params),
        queryFn: () => listContactSectionsApiV1MeContactsGet(params),
        staleTime: PAGE_STALE_MS,
      });
    },
    [queryClient]
  );
};

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
