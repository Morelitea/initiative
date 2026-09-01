import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

import { validatePage } from "@/lib/routeSearch";
import { isSearchTab, type SearchTab } from "@/lib/searchResults";

/** What the reader searched for, which slice they are reading, and how far in.
 *  All optional — `/search` with nothing on it is the empty search page. */
export interface SearchPageSearch {
  q?: string;
  tab?: SearchTab;
  page?: number;
}

export const Route = createFileRoute("/_serverRequired/_authenticated/g/$guildId/search")({
  validateSearch: (search: Record<string, unknown>): SearchPageSearch => ({
    q: typeof search.q === "string" && search.q.length > 0 ? search.q : undefined,
    // `all` is the default, so it stays out of the URL.
    tab: isSearchTab(search.tab) && search.tab !== "all" ? search.tab : undefined,
    page: validatePage(search.page),
  }),
  component: lazyRouteComponent(() =>
    import("@/pages/SearchPage").then((m) => ({ default: m.SearchPage }))
  ),
});
