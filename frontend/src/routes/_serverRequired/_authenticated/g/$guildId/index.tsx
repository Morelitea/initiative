import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

import { validatePage } from "@/lib/routeSearch";

export const Route = createFileRoute("/_serverRequired/_authenticated/g/$guildId/")({
  /** `tool` is a tool's route segment ("projects", "counter-groups", …). It is
   *  passed through as-is; the page resolves it against the tool registry and
   *  falls back to the first tool the user can actually see. */
  validateSearch: (search: Record<string, unknown>): { tool?: string; page?: number } => ({
    tool: typeof search.tool === "string" ? search.tool : undefined,
    page: validatePage(search.page),
  }),
  component: lazyRouteComponent(() =>
    import("@/pages/GuildHomePage").then((m) => ({ default: m.GuildHomePage }))
  ),
});
