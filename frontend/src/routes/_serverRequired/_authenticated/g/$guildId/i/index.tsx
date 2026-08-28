import { createFileRoute, redirect } from "@tanstack/react-router";

/**
 * The initiatives list moved onto the guild home page, which now holds the
 * whole list — the ones you're in and the ones you can join — so this address
 * forwards there. `?create=true` is carried across so an old link (a sidebar
 * bookmark, a notification) still opens the create dialog on arrival.
 *
 * Only the list moved: `/g/{guildId}/i/{initiativeId}` and everything under it
 * are untouched.
 */
export function guildHomeRedirectSearch(search: { create?: string }): { create?: string } {
  return search.create === "true" ? { create: "true" } : {};
}

export const Route = createFileRoute("/_serverRequired/_authenticated/g/$guildId/i/")({
  validateSearch: (search: Record<string, unknown>): { create?: string } => ({
    create: typeof search.create === "string" ? search.create : undefined,
  }),
  beforeLoad: ({ params, search }) => {
    throw redirect({
      to: "/g/$guildId",
      params: { guildId: params.guildId },
      search: guildHomeRedirectSearch(search),
    });
  },
});
