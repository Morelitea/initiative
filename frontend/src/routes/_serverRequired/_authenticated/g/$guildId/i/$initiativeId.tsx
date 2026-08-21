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
export const Route = createFileRoute("/_serverRequired/_authenticated/g/$guildId/i/$initiativeId")({
  loader: async ({ context, params }) => {
    const { queryClient } = context;
    const guildId = Number(params.guildId);

    // Prefetch in background - don't block navigation on failure
    try {
      await queryClient.ensureQueryData({
        queryKey: getListInitiativesApiV1GGuildIdInitiativesGetQueryKey(guildId),
        queryFn: () => listInitiativesApiV1GGuildIdInitiativesGet(guildId),
        staleTime: 30_000,
      });
    } catch {
      // Silently fail - component will fetch its own data
    }
  },
  component: Outlet,
});
