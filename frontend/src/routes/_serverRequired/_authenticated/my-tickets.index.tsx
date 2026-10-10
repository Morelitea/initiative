import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export interface MyTicketsSearch {
  /** Open a filing form on arrival. ``security`` is what the server's
   *  ``/.well-known/security.txt`` links to. */
  report?: "security";
}

export const Route = createFileRoute("/_serverRequired/_authenticated/my-tickets/")({
  validateSearch: (search: Record<string, unknown>): MyTicketsSearch =>
    search.report === "security" ? { report: "security" } : {},
  component: lazyRouteComponent(() =>
    import("@/pages/user/MyTicketsPage").then((m) => ({ default: m.MyTicketsPage }))
  ),
});
