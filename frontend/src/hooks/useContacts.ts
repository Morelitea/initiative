/**
 * The two reads and one write behind My Contacts.
 *
 * The sections are a single server-side aggregate — the backend walks the
 * reader's communities the way every other "my" page does — and the starred
 * list is a second read, because a favorite may be somebody you share no
 * community with.
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
import type { ContactGuildSection } from "@/api/generated/initiativeAPI.schemas";

/** Members fetched per community at a time. */
export const CONTACTS_PAGE_SIZE = 20;

const sectionParams = (search: string) =>
  search.trim() ? { search, page_size: CONTACTS_PAGE_SIZE } : { page_size: CONTACTS_PAGE_SIZE };

const favoriteParams = (search: string) => (search.trim() ? { search } : undefined);

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

/**
 * One more page of a single community.
 *
 * Deliberately not a query: a section is read forward and appended to, so the
 * page owns the accumulation rather than holding a query per community.
 */
export const fetchContactPage = async (
  guildId: number,
  page: number,
  search: string
): Promise<ContactGuildSection | undefined> => {
  const response = await listContactSectionsApiV1MeContactsGet({
    guild_ids: [guildId],
    page,
    page_size: CONTACTS_PAGE_SIZE,
    ...(search.trim() ? { search } : {}),
  });
  return response.sections[0];
};
