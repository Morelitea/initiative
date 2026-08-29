import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

import { validatePage } from "@/lib/routeSearch";

export const Route = createFileRoute("/_serverRequired/_authenticated/g/$guildId/")({
  /** `tool` is a tool's route segment ("projects", "counter-groups", …). It is
   *  passed through as-is; the page resolves it against the tool registry and
   *  falls back to the first tool the user can actually see. */
  /** `create=true` opens the new-initiative dialog once on arrival — the deep
   *  link the sidebar uses, and what the retired `/i` list route forwards. */
  /** `q`, `sort` and `dir` are the table's search box and its order. They ride
   *  in the address so a narrowed, re-ordered table is a link; the page
   *  resolves an unknown `sort` back to its default rather than refusing it. */
  validateSearch: (
    search: Record<string, unknown>
  ): {
    tool?: string;
    page?: number;
    create?: string;
    q?: string;
    sort?: string;
    dir?: string;
  } => ({
    tool: typeof search.tool === "string" ? search.tool : undefined,
    page: validatePage(search.page),
    create: search.create === "true" ? "true" : undefined,
    q: typeof search.q === "string" && search.q ? search.q : undefined,
    sort: typeof search.sort === "string" ? search.sort : undefined,
    dir: search.dir === "asc" || search.dir === "desc" ? search.dir : undefined,
  }),
  component: lazyRouteComponent(() =>
    import("@/pages/GuildHomePage").then((m) => ({ default: m.GuildHomePage }))
  ),
});
