import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

import { validatePage } from "@/lib/routeSearch";

/** What the reader is looking for and how far in. Both stay out of the URL at
 *  their defaults, so a plain `/members` is the first page of everybody. */
export interface GuildMembersSearch {
  q?: string;
  page?: number;
}

export const Route = createFileRoute("/_serverRequired/_authenticated/c/$guildId/members")({
  validateSearch: (search: Record<string, unknown>): GuildMembersSearch => ({
    q: typeof search.q === "string" && search.q.length > 0 ? search.q : undefined,
    page: validatePage(search.page),
  }),
  component: lazyRouteComponent(() =>
    import("@/pages/GuildMembersPage").then((m) => ({ default: m.GuildMembersPage }))
  ),
});
