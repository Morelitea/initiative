import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

type MyTasksSearchParams = {
  page?: number;
  authenticated?: string;
};

export const Route = createFileRoute("/_serverRequired/_authenticated/")({
  validateSearch: (search: Record<string, unknown>): MyTasksSearchParams => ({
    page:
      typeof search.page === "number" && search.page >= 1
        ? search.page
        : typeof search.page === "string" && Number(search.page) >= 1
          ? Number(search.page)
          : undefined,
    authenticated: typeof search.authenticated === "string" ? search.authenticated : undefined,
  }),
  component: lazyRouteComponent(() =>
    import("@/pages/MyTasksPage").then((m) => ({ default: m.MyTasksPage }))
  ),
});
