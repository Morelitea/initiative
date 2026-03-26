import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

type EventsSearchParams = {
  create?: string;
  initiativeId?: string;
  page?: number;
};

export const Route = createFileRoute("/_serverRequired/_authenticated/g/$guildId/events")({
  validateSearch: (search: Record<string, unknown>): EventsSearchParams => ({
    create: typeof search.create === "string" ? search.create : undefined,
    initiativeId: typeof search.initiativeId === "string" ? search.initiativeId : undefined,
    page:
      typeof search.page === "number" && search.page >= 1
        ? search.page
        : typeof search.page === "string" && Number(search.page) >= 1
          ? Number(search.page)
          : undefined,
  }),
  component: lazyRouteComponent(() =>
    import("@/pages/initiativeTools/events/EventsPage").then((m) => ({ default: m.EventsPage }))
  ),
});
