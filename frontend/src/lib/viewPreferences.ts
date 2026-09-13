/**
 * The user's view-preference map, addressed outside React.
 *
 * The cache key and the eager fetch live here rather than in
 * `@/hooks/useViewPreference` so that `useAuth` — which starts the fetch the
 * moment it knows who is signed in — does not have to import a module that
 * imports `useAuth` back.
 */

import type { UserViewPreferencesMap } from "@/api/generated/initiativeAPI.schemas";
import {
  getListViewPreferencesApiV1UserViewPreferencesGetQueryKey,
  listViewPreferencesApiV1UserViewPreferencesGet,
} from "@/api/generated/user-view-preferences/user-view-preferences";
import { queryClient } from "@/lib/queryClient";

/**
 * The cache key for the full preferences map. Exported so the one-shot
 * localStorage migration can prime the cache before the query runs.
 */
export const VIEW_PREFERENCES_QUERY_KEY =
  getListViewPreferencesApiV1UserViewPreferencesGetQueryKey();

/**
 * Filter state changes rarely from the server's perspective; this client owns
 * the source of truth and writes through, so a long stale time is fine.
 */
export const PREFERENCES_STALE_TIME_MS = 5 * 60 * 1000;

/**
 * Start the preference map fetch without waiting for a screen to ask for it.
 *
 * Consumers that gate a list query on their saved filters — My Tasks holds its
 * table back until its sort is in hand, because the table seeds its headers at
 * mount — otherwise turn this into a serial hop: authenticate, then fetch
 * preferences, then fetch the list. Called as soon as the signed-in account is
 * known, the map is already in flight (usually already answered) by the time
 * the landing page mounts, and `useViewPreference`'s own query dedupes onto it.
 *
 * Errors are swallowed: nothing waits on this, and every consumer falls back to
 * its defaults when the map cannot be read.
 */
export const prefetchViewPreferences = (): void => {
  void queryClient
    .prefetchQuery<UserViewPreferencesMap>({
      queryKey: VIEW_PREFERENCES_QUERY_KEY,
      queryFn: ({ signal }) => listViewPreferencesApiV1UserViewPreferencesGet(undefined, signal),
      staleTime: PREFERENCES_STALE_TIME_MS,
    })
    .catch(() => {});
};
