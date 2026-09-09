import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

import { type PageSearch, validatePage } from "@/lib/routeSearch";

/**
 * There is deliberately no loader here.
 *
 * This route used to prefetch the task list under a hand-written key —
 * `["tasks", "me", "assigned", …]` — while the page reads it through
 * `useGlobalTasksTable`, which asks under the generated key for
 * `/api/v1/me/tasks`. The two never met: every visit paid for a request whose
 * answer nothing looked at, and because the key was not a request path the
 * offline cache would not persist it either. The page owns this read.
 */
export const Route = createFileRoute("/_serverRequired/_authenticated/")({
  validateSearch: (search: Record<string, unknown>): PageSearch => ({
    page: validatePage(search.page),
  }),
  component: lazyRouteComponent(() =>
    import("@/pages/user/MyTasksPage").then((m) => ({ default: m.MyTasksPage }))
  ),
});
