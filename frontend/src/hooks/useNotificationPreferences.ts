import { useQuery, useQueryClient } from "@tanstack/react-query";

import type {
  NotificationPreferencesRead,
  NotificationPreferencesUpdate,
} from "@/api/generated/initiativeAPI.schemas";
import {
  getReadMyNotificationPreferencesApiV1MeNotificationPreferencesGetQueryKey,
  readMyNotificationPreferencesApiV1MeNotificationPreferencesGet,
  updateMyNotificationPreferencesApiV1MeNotificationPreferencesPut,
} from "@/api/generated/notifications/notifications";
import { useApiMutation } from "@/hooks/useApiMutation";
import type { MutationOpts } from "@/types/mutation";

/**
 * The settings page's whole state: the category registry, this account's
 * overrides, its quiet hours, and each community's level.
 *
 * The registry travels with the response, so the page renders the categories
 * this build has rather than carrying a copy of the list.
 */
export const useNotificationPreferences = (options?: { enabled?: boolean }) =>
  useQuery<NotificationPreferencesRead>({
    queryKey: getReadMyNotificationPreferencesApiV1MeNotificationPreferencesGetQueryKey(),
    queryFn: () => readMyNotificationPreferencesApiV1MeNotificationPreferencesGet(),
    enabled: options?.enabled,
  });

/**
 * Move some switches.
 *
 * A partial write — one switch is one request — so two open settings tabs
 * cannot overwrite each other's unrelated rows. The response is the whole
 * settled document, which is what the cache takes.
 */
export const useUpdateNotificationPreferences = (
  options?: MutationOpts<NotificationPreferencesRead, NotificationPreferencesUpdate>
) => {
  const client = useQueryClient();
  return useApiMutation<NotificationPreferencesRead, NotificationPreferencesUpdate>(
    {
      mutationFn: (payload) =>
        updateMyNotificationPreferencesApiV1MeNotificationPreferencesPut(payload),
    },
    {
      ...options,
      onSuccess: (...args) => {
        const [settled] = args;
        // The server answered with the whole document, so there is nothing to
        // refetch — writing it straight in keeps the grid from flickering back
        // through a loading state on every switch.
        client.setQueryData(
          getReadMyNotificationPreferencesApiV1MeNotificationPreferencesGetQueryKey(),
          settled
        );
        options?.onSuccess?.(...args);
      },
    }
  );
};
