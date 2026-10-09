/**
 * One person's view of a project's tasks: which of the project's views they
 * are in, and the filters it shows them — their own for that view, or the
 * view's — ranked against the URL and the project's default view.
 *
 * The project page reads it to show the list, and the project's export card
 * reads it so an export starts from the same tasks.
 */

import { useCallback, useMemo } from "react";

import type {
  TaskFilterSpec as ApiTaskFilterSpec,
  SortField,
  TaskStatusRead,
  ToolViewRead,
  ViewLayoutType,
} from "@/api/generated/initiativeAPI.schemas";
import { usePersistedTableState } from "@/hooks/usePersistedTableState";
import { useProjectTaskStatuses } from "@/hooks/useProjects";
import { useProjectViews } from "@/hooks/useProjectViews";
import { useTags } from "@/hooks/useTags";
import { useViewPreference } from "@/hooks/useViewPreference";
import {
  EMPTY_TASK_FILTERS,
  specFromApi,
  type TaskFilterSpec,
  taskFiltersEqual,
  taskSortFields,
} from "@/lib/filters/taskFilters";
import { resolveViewState, type StoredViews, type ViewSearch, viewLink } from "@/lib/filters/views";

/** A project's view, with its fixed filters as the task filter spec. */
export type ProjectView = ToolViewRead & { filters: TaskFilterSpec };

/** Where one person's own state for a project's views is kept. */
export const projectViewsPreferenceKey = (projectId: number) => `project:${projectId}:views`;

/**
 * Coerce whatever comes back from the server into this person's views state,
 * or null when nothing is stored. Drops anything with the wrong type, so a
 * stale or corrupted blob can't crash the UI.
 */
export function sanitizeStoredViews(raw: unknown): StoredViews<TaskFilterSpec> | null {
  if (raw === null || typeof raw !== "object") return null;
  const parsed = raw as { view?: unknown; filters?: unknown };
  const filters: Record<string, TaskFilterSpec> = {};
  if (parsed.filters !== null && typeof parsed.filters === "object") {
    for (const [slug, spec] of Object.entries(parsed.filters)) {
      if (spec !== null && typeof spec === "object") {
        filters[slug] = specFromApi(spec as ApiTaskFilterSpec);
      }
    }
  }
  return { view: typeof parsed.view === "string" ? parsed.view : null, filters };
}

/** A set's views with their filters as specs, in order. */
export const projectViews = (views: readonly ToolViewRead[] | undefined): ProjectView[] =>
  (views ?? []).map((view) => ({ ...view, filters: specFromApi(view.definition.filters) }));

export function useProjectTaskView({
  projectId,
  taskStatuses,
  search,
}: {
  projectId: number;
  /** The project's statuses, to drop a filter on one that is gone. */
  taskStatuses: TaskStatusRead[];
  /** What the URL names, which a link means for whoever opens it. */
  search: ViewSearch;
}) {
  const [storedRaw, setStored, { isLoaded: filtersLoaded }] = useViewPreference<unknown>(
    projectViewsPreferenceKey(projectId),
    null
  );
  const stored = useMemo(() => sanitizeStoredViews(storedRaw), [storedRaw]);

  // The project's shared views. `can_configure` is computed server-side and is
  // what gates every curation affordance.
  const viewsQuery = useProjectViews(projectId);
  // Settled either way: a set that cannot be read leaves every task in a
  // table, rather than no list at all.
  const viewsLoaded = viewsQuery.isSuccess || viewsQuery.isError;
  const canConfigure = viewsQuery.data?.can_configure ?? false;
  const views = useMemo(() => projectViews(viewsQuery.data?.views), [viewsQuery.data]);

  // URL first (a link means the same thing for whoever opens it), then the
  // view this person was last in, then the project's default. See
  // lib/filters/views.
  const { view, spec, modified, unresolvedView } = useMemo(
    () =>
      resolveViewState({
        search,
        views,
        stored: filtersLoaded ? stored : null,
        emptySpec: EMPTY_TASK_FILTERS,
        equals: taskFiltersEqual,
      }),
    [search, views, stored, filtersLoaded]
  );

  /** Record `patch` for this person, keeping only their filters for views the
   *  project still has. */
  const writeStored = useCallback(
    (patch: (current: StoredViews<TaskFilterSpec>) => StoredViews<TaskFilterSpec>) =>
      setStored((prev: unknown) => {
        const current = sanitizeStoredViews(prev) ?? { view: null, filters: {} };
        const next = patch(current);
        if (views.length === 0) return next;
        return {
          ...next,
          filters: Object.fromEntries(
            Object.entries(next.filters).filter(([slug]) =>
              views.some((each) => each.slug === slug)
            )
          ),
        };
      }),
    [setStored, views]
  );

  /** Keep `next` as this person's own filters for the view on screen, or drop
   *  theirs (null) to go back to the view's. */
  const setOwnFilters = useCallback(
    (next: TaskFilterSpec | null) => {
      if (!view) return;
      writeStored(({ filters }) => {
        const others = Object.entries(filters).filter(([slug]) => slug !== view.slug);
        return {
          view: view.slug,
          filters: Object.fromEntries(next ? [...others, [view.slug, next]] : others),
        };
      });
    },
    [view, writeStored]
  );

  /** Make `slug` the view this person comes back to, dropping their own
   *  filters for it when they arrived by a link that names it. */
  const rememberView = useCallback(
    (slug: string, dropOwnFilters = false) =>
      writeStored(({ filters }) => ({
        view: slug,
        filters: dropOwnFilters
          ? Object.fromEntries(Object.entries(filters).filter(([each]) => each !== slug))
          : filters,
      })),
    [writeStored]
  );

  /** What `?view=` carries for the view `slug`, when a link can name it. A
   *  view just saved is named as it is, until the set it is in arrives. */
  const linkFor = useCallback(
    (slug: string) => {
      const named = views.find((each) => each.slug === slug);
      return named
        ? viewLink(named, views, { emptySpec: EMPTY_TASK_FILTERS, equals: taskFiltersEqual })
        : slug;
    },
    [views]
  );

  /** Whether this person keeps filters of their own for `slug`. */
  const hasOwnFilters = useCallback(
    (slug: string) => stored !== null && Object.hasOwn(stored.filters, slug),
    [stored]
  );

  // Fetch community tags for filtering
  const { data: tags = [], isSuccess: tagsLoaded, isError: tagsFailed } = useTags();

  /**
   * The filters actually applied, with ids that no longer resolve dropped.
   *
   * A deleted tag or a removed status does NOT quietly stop narrowing: it is
   * still sent as `tag_ids in (42)`, which matches nothing, so the list goes
   * empty and the control that would explain why has no option left to render.
   *
   * Pruning is derived rather than written back — the values may have come
   * from a shared view, and rewriting that on someone's behalf (or marking
   * it modified) is not this component's call. Editing any filter persists the
   * pruned set, so it heals on the first change.
   *
   * The two lookups fail differently. Statuses arrive as a prop, so an empty
   * list means "not loaded yet" and nothing is pruned. Tags are fetched: while
   * that request is in flight the filter stands, but if it *fails* the tag
   * filter is dropped rather than trusted, because an id that cannot be
   * checked is an id that may be hiding every task in the project. Showing
   * more than was asked for is recoverable; showing an unexplained empty list
   * is not.
   */
  const appliedSpec = useMemo(() => {
    const statusIds = new Set(taskStatuses.map((status) => status.id));
    const status_ids =
      taskStatuses.length > 0 ? spec.status_ids.filter((id) => statusIds.has(id)) : spec.status_ids;

    let tag_ids = spec.tag_ids;
    if (tagsLoaded) {
      const tagIds = new Set(tags.map((tag) => tag.id));
      tag_ids = spec.tag_ids.filter((id) => tagIds.has(id));
    } else if (tagsFailed) {
      tag_ids = [];
    }

    if (tag_ids.length === spec.tag_ids.length && status_ids.length === spec.status_ids.length) {
      return spec;
    }
    return { ...spec, tag_ids, status_ids };
  }, [spec, tags, tagsLoaded, tagsFailed, taskStatuses]);

  return {
    filtersLoaded,
    viewsLoaded,
    views,
    canConfigure,
    view,
    layout: view?.definition.layout.type ?? "table",
    spec,
    modified,
    unresolvedView,
    appliedSpec,
    setOwnFilters,
    rememberView,
    hasOwnFilters,
    linkFor,
  };
}

export const projectTaskTableKey = (projectId: number, viewSlug: string) =>
  `initiative-project-${projectId}-${viewSlug}-task-table`;

/** Which column one view of a project's task table is grouped and sorted by,
 *  as the reader left it. Kept beside the table's column-visibility map so the
 *  whole "how this list is shown" answer survives a reload together. */
export const useProjectTaskTableState = (projectId: number, viewSlug: string) =>
  usePersistedTableState(projectTaskTableKey(projectId, viewSlug));

/** The order a view lists tasks in, as the endpoint's `sorting`: the table's
 *  own sort while it is the layout, and the project's order in every other. */
export const taskViewSorting = (
  layout: ViewLayoutType,
  tableSorting: Parameters<typeof taskSortFields>[0]
): SortField[] => (layout === "table" ? taskSortFields(tableSorting) : []);

/** What an export of the project starts from for this person: the tasks and
 *  the order their view of it shows, with the statuses those filters name. */
export function useProjectTaskExportView(projectId: number) {
  const taskStatuses = useProjectTaskStatuses(projectId).data ?? EMPTY_STATUSES;
  const { appliedSpec, layout, view } = useProjectTaskView({
    projectId,
    taskStatuses,
    search: NO_SEARCH,
  });
  const [{ sorting }] = useProjectTaskTableState(projectId, view?.slug ?? "");
  return useMemo(
    () => ({ tasks: appliedSpec, taskSorting: taskViewSorting(layout, sorting), taskStatuses }),
    [appliedSpec, layout, sorting, taskStatuses]
  );
}

const EMPTY_STATUSES: TaskStatusRead[] = [];
const NO_SEARCH = {};
