import { createFileRoute, Outlet } from "@tanstack/react-router";

import {
  getListInitiativesApiV1GGuildIdInitiativesGetQueryKey,
  listInitiativesApiV1GGuildIdInitiativesGet,
} from "@/api/generated/initiatives/initiatives";

/**
 * Layout for everything addressed inside one initiative — the initiative page,
 * its six tool tabs, and every tool entity beneath them.
 *
 * Deliberately chrome-free: it warms the initiative list (which names the
 * initiative, and which every nested page reads) and renders the outlet. The
 * header and tab strip belong to the initiative page itself, so a project or a
 * task doesn't inherit a tab bar it isn't part of.
 */
export const Route = createFileRoute("/_serverRequired/_authenticated/c/$guildId/i/$initiativeId")({
  loader: ({ context, params }) => {
    const { queryClient } = context;
    const guildId = Number(params.guildId);

    // Warm the cache without holding the navigation on it: the page draws
    // its placeholder at once and the list lands into it. A failed prefetch
    // is swallowed here; the page fetches for itself and reports the error.
    void queryClient.prefetchQuery({
      queryKey: getListInitiativesApiV1GGuildIdInitiativesGetQueryKey(guildId),
      queryFn: () => listInitiativesApiV1GGuildIdInitiativesGet(guildId),
      staleTime: 30_000,
    });
  },
  component: Outlet,
});
