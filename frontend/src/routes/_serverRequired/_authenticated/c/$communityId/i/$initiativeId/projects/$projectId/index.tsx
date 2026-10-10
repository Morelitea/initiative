import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

import type { ProjectRead, UserViewPreferencesMap } from "@/api/generated/initiativeAPI.schemas";
import { getReadProjectQueryKey, readProject } from "@/api/generated/projects/projects";
import {
  getListTaskStatusesQueryKey,
  listTaskStatuses,
} from "@/api/generated/task-statuses/task-statuses";
import {
  projectViews,
  projectViewsPreferenceKey,
  sanitizeStoredViews,
} from "@/hooks/useProjectTaskView";
import { projectViewsQuery } from "@/hooks/useToolLayouts";
import { tasksQuery } from "@/hooks/useTasks";
import { VIEW_PREFERENCES_QUERY_KEY } from "@/hooks/useViewPreference";
import {
  buildTaskListParams,
  EMPTY_TASK_FILTERS,
  taskFiltersEqual,
} from "@/lib/filters/taskFilters";
import { parseViewSlug } from "@/lib/filters/viewSearch";
import { resolveViewState } from "@/lib/filters/views";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/i/$initiativeId/projects/$projectId/"
)({
  validateSearch: (search: Record<string, unknown>) => ({
    create: typeof search.create === "string" ? search.create : undefined,
    // Which of the project's views it shows, which makes it linkable. A link
    // from before views names a preset instead, which became the view with
    // its slug. Malformed values are dropped, never thrown — a pasted link
    // with a typo should still render the project.
    view: parseViewSlug(search.view),
    preset: parseViewSlug(search.preset),
  }),
  // The prefetch depends on the search params, so the loader has to see them.
  loaderDeps: ({ search }) => search,
  loader: ({ context, params, deps }) => {
    const projectId = Number(params.projectId);
    const communityId = Number(params.communityId);
    const { queryClient } = context;

    // Warm the cache without holding the navigation on it: the page draws
    // its placeholder at once and the reads land into it. A failed prefetch
    // is swallowed here; the page fetches for itself and reports the error.
    void (async () => {
      try {
        const [, set] = await Promise.all([
          queryClient.ensureQueryData<ProjectRead>({
            queryKey: getReadProjectQueryKey(communityId, projectId),
            queryFn: () => readProject(communityId, projectId),
            staleTime: 30_000,
          }),
          queryClient.ensureQueryData({
            ...projectViewsQuery(communityId, projectId),
            staleTime: 60_000,
          }),
          queryClient.ensureQueryData({
            queryKey: getListTaskStatusesQueryKey(communityId, projectId),
            queryFn: () => listTaskStatuses(communityId, projectId),
            staleTime: 60_000,
          }),
        ]);

        // Resolve exactly the way the section does, and build the params with the
        // same function, so the prefetch lands on the key the component asks for.
        // These used to be two separate implementations that had drifted, and the
        // prefetched entry was never read.
        const { spec } = resolveViewState({
          search: deps,
          views: projectViews(set.views),
          stored: sanitizeStoredViews(
            queryClient.getQueryData<UserViewPreferencesMap>(VIEW_PREFERENCES_QUERY_KEY)?.items?.[
              projectViewsPreferenceKey(projectId)
            ]
          ),
          emptySpec: EMPTY_TASK_FILTERS,
          equals: taskFiltersEqual,
        });
        const taskParams = buildTaskListParams(spec, { projectId });

        // Deliberately not awaited: re-running the loader on a view change must
        // not block the navigation on a task refetch.
        void queryClient.ensureQueryData({
          ...tasksQuery(communityId, taskParams),
          staleTime: 30_000,
        });
      } catch {
        // Silently fail - component will fetch its own data
      }
    })();
  },
  component: lazyRouteComponent(() =>
    import("@/pages/initiativeTools/projects/ProjectDetailPage").then((m) => ({
      default: m.ProjectDetailPage,
    }))
  ),
});
