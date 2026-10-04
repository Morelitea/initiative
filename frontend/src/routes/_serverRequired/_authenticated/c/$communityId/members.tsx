import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

import { validatePage } from "@/lib/routeSearch";

/** What the reader is looking for and how far in. Both stay out of the URL at
 *  their defaults, so a plain `/members` is the first page of everybody. */
export interface CommunityMembersSearch {
  q?: string;
  page?: number;
}

export const Route = createFileRoute("/_serverRequired/_authenticated/c/$communityId/members")({
  validateSearch: (search: Record<string, unknown>): CommunityMembersSearch => ({
    q: typeof search.q === "string" && search.q.length > 0 ? search.q : undefined,
    page: validatePage(search.page),
  }),
  component: lazyRouteComponent(() =>
    import("@/pages/CommunityMembersPage").then((m) => ({ default: m.CommunityMembersPage }))
  ),
});
