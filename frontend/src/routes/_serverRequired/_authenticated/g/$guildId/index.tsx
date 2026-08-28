import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

import { validatePage } from "@/lib/routeSearch";

export const Route = createFileRoute("/_serverRequired/_authenticated/g/$guildId/")({
  /** `tool` is a tool's route segment ("projects", "counter-groups", …). It is
   *  passed through as-is; the page resolves it against the tool registry and
   *  falls back to the first tool the user can actually see. */
  /** `create=true` opens the new-initiative dialog once on arrival — the deep
   *  link the sidebar uses, and what the retired `/i` list route forwards. */
  validateSearch: (
    search: Record<string, unknown>
  ): { tool?: string; page?: number; create?: string } => ({
    tool: typeof search.tool === "string" ? search.tool : undefined,
    page: validatePage(search.page),
    create: search.create === "true" ? "true" : undefined,
  }),
  component: lazyRouteComponent(() =>
    import("@/pages/GuildHomePage").then((m) => ({ default: m.GuildHomePage }))
  ),
});
