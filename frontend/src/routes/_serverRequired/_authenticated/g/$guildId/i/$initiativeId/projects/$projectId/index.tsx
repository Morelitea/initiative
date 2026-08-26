import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

import {
  getListFilterPresetsApiV1GGuildIdProjectsProjectIdFilterPresetsGetQueryKey,
  listFilterPresetsApiV1GGuildIdProjectsProjectIdFilterPresetsGet,
} from "@/api/generated/filter-presets/filter-presets";
import type {
  FilterPresetListResponse,
  ProjectRead,
  UserViewPreferencesMap,
} from "@/api/generated/initiativeAPI.schemas";
import {
  getReadProjectApiV1GGuildIdProjectsProjectIdGetQueryKey,
  readProjectApiV1GGuildIdProjectsProjectIdGet,
} from "@/api/generated/projects/projects";
import {
  getListTaskStatusesApiV1GGuildIdProjectsProjectIdTaskStatusesGetQueryKey,
  listTaskStatusesApiV1GGuildIdProjectsProjectIdTaskStatusesGet,
} from "@/api/generated/task-statuses/task-statuses";
import {
  getListTasksApiV1GGuildIdTasksGetQueryKey,
  listTasksApiV1GGuildIdTasksGet,
} from "@/api/generated/tasks/tasks";
import { VIEW_PREFERENCES_QUERY_KEY } from "@/hooks/useViewPreference";
import { fetchAllPages } from "@/lib/fetchAllPages";
import { resolvePresetState } from "@/lib/filters/presets";
import {
  buildTaskListParams,
  EMPTY_TASK_FILTERS,
  specFromApi,
  TASK_VIEW_MODES,
  type TaskFilterSpec,
  type TaskViewMode,
  taskFiltersEqual,
} from "@/lib/filters/taskFilters";
import { parsePresetSlug, parseViewMode } from "@/lib/filters/viewSearch";
import { getItem } from "@/lib/storage";

/** The viewer's remembered filter state, from the hydrated preferences cache
 *  (or legacy localStorage if they haven't written it back yet). */
function storedSpec(
  queryClient: { getQueryData: <T>(key: readonly unknown[]) => T | undefined },
  projectId: number
): { spec: TaskFilterSpec; viewMode?: TaskViewMode; activePresetSlug?: string | null } | null {
  const scopeKey = `project:${projectId}:view-filters`;
  let raw = queryClient.getQueryData<UserViewPreferencesMap>(VIEW_PREFERENCES_QUERY_KEY)?.items?.[
    scopeKey
  ];
  if (raw === undefined) {
    try {
      const local = getItem(scopeKey);
      raw = local ? JSON.parse(local) : undefined;
    } catch {
      raw = undefined;
    }
  }
  if (raw === null || typeof raw !== "object") return null;
  const parsed = raw as Record<string, unknown>;
  return {
    spec: specFromApi(parsed as never),
    viewMode: parseViewMode(parsed.viewMode, TASK_VIEW_MODES),
    activePresetSlug: typeof parsed.activePresetSlug === "string" ? parsed.activePresetSlug : null,
  };
}

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/g/$guildId/i/$initiativeId/projects/$projectId/"
)({
  validateSearch: (search: Record<string, unknown>) => ({
    create: typeof search.create === "string" ? search.create : undefined,
    // What makes a task view linkable: which saved preset it shows, and which
    // view it is in. Malformed values are dropped, never thrown — a pasted
    // link with a typo should still render the project.
    preset: parsePresetSlug(search.preset),
    view: parseViewMode(search.view, TASK_VIEW_MODES),
  }),
  // The prefetch depends on the search params, so the loader has to see them.
  loaderDeps: ({ search }) => search,
  loader: async ({ context, params, deps }) => {
    const projectId = Number(params.projectId);
    const guildId = Number(params.guildId);
    const { queryClient } = context;

    // Prefetch in background - don't block navigation on failure
    try {
      const [project, presets] = await Promise.all([
        queryClient.ensureQueryData<ProjectRead>({
          queryKey: getReadProjectApiV1GGuildIdProjectsProjectIdGetQueryKey(guildId, projectId),
          queryFn: () => readProjectApiV1GGuildIdProjectsProjectIdGet(guildId, projectId),
          staleTime: 30_000,
        }),
        queryClient.ensureQueryData<FilterPresetListResponse>({
          queryKey: getListFilterPresetsApiV1GGuildIdProjectsProjectIdFilterPresetsGetQueryKey(
            guildId,
            projectId
          ),
          queryFn: () =>
            listFilterPresetsApiV1GGuildIdProjectsProjectIdFilterPresetsGet(guildId, projectId),
          staleTime: 60_000,
        }),
        queryClient.ensureQueryData({
          queryKey: getListTaskStatusesApiV1GGuildIdProjectsProjectIdTaskStatusesGetQueryKey(
            guildId,
            projectId
          ),
          queryFn: () =>
            listTaskStatusesApiV1GGuildIdProjectsProjectIdTaskStatusesGet(guildId, projectId),
          staleTime: 60_000,
        }),
      ]);

      // Resolve exactly the way the section does, and build the params with the
      // same function, so the prefetch lands on the key the component asks for.
      // These used to be two separate implementations that had drifted, and the
      // prefetched entry was never read.
      const { spec } = resolvePresetState<TaskFilterSpec, TaskViewMode>({
        search: deps,
        presets: (presets.items ?? []).map((preset) => ({
          ...preset,
          filters: specFromApi(preset.filters),
        })),
        stored: storedSpec(queryClient, projectId),
        allowedViews: TASK_VIEW_MODES,
        defaultView: project.default_view_mode,
        fallbackView: "table",
        emptySpec: EMPTY_TASK_FILTERS,
        equals: taskFiltersEqual,
      });
      const taskParams = buildTaskListParams(spec, { projectId });

      // Deliberately not awaited: re-running the loader on a preset change must
      // not block the navigation on a task refetch.
      void queryClient.ensureQueryData({
        queryKey: getListTasksApiV1GGuildIdTasksGetQueryKey(guildId, taskParams),
        // page_size=0 walks the server's fetch-all windows for the full set
        // (same queryFn shape as useTasks, which shares this cache key).
        queryFn: () => fetchAllPages(listTasksApiV1GGuildIdTasksGet, guildId, taskParams),
        staleTime: 30_000,
      });
    } catch {
      // Silently fail - component will fetch its own data
    }
  },
  component: lazyRouteComponent(() =>
    import("@/pages/ProjectDetailPage").then((m) => ({ default: m.ProjectDetailPage }))
  ),
});
