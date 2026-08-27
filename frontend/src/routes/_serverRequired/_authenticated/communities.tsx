import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

import type { GuildCategory } from "@/api/generated/initiativeAPI.schemas";
import { asGuildCategory } from "@/lib/guildCategories";

export const Route = createFileRoute("/_serverRequired/_authenticated/communities")({
  // Which shelf is showing, so a filtered directory can be linked and survives
  // a reload. Anything unrecognized falls back to "all" rather than filtering
  // the grid down to nothing.
  validateSearch: (search: Record<string, unknown>): { category?: GuildCategory } => {
    const category = asGuildCategory(search.category);
    return category ? { category } : {};
  },
  component: lazyRouteComponent(() =>
    import("@/pages/communities/CommunitiesPage").then((m) => ({
      default: m.CommunitiesPage,
    }))
  ),
});
