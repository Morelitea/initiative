import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

import type { GuildCategory } from "@/api/generated/initiativeAPI.schemas";
import { asGuildCategory } from "@/lib/guildCategories";

/** What the endpoint accepts, so a hand-typed address cannot ask for more. */
const MAX_QUERY_LENGTH = 200;

export interface CommunitySearch {
  category?: GuildCategory;
  q?: string;
}

export const Route = createFileRoute("/_serverRequired/_authenticated/communities")({
  // What is showing, so a filtered directory can be linked and survives a
  // reload. Both live here rather than in component state because the filters
  // and the results they narrow sit on opposite sides of the app layout — the
  // sidebar writes these, the page reads them. Anything unrecognized falls
  // back to the unfiltered shelf rather than filtering the grid down to
  // nothing.
  validateSearch: (search: Record<string, unknown>): CommunitySearch => {
    const category = asGuildCategory(search.category);
    const raw = typeof search.q === "string" ? search.q.slice(0, MAX_QUERY_LENGTH) : "";
    return {
      ...(category ? { category } : {}),
      ...(raw.trim() ? { q: raw } : {}),
    };
  },
  component: lazyRouteComponent(() =>
    import("@/pages/communities/CommunitiesPage").then((m) => ({
      default: m.CommunitiesPage,
    }))
  ),
});
