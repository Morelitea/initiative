/**
 * One person's view of a project's tasks: which of the project's list layouts
 * they are in, and their own filters and sort for each, saved for them on the
 * project (a per-user preference). A layout is how the project draws its
 * tasks; what a person narrows the list to and how they order it are theirs.
 * A layout's presets are where they can start from: picking one makes its
 * filters and sort theirs.
 *
 * The project page reads it to show the list, and the project's export card
 * reads it so an export starts from the same tasks.
 */

import type { SortingState } from "@tanstack/react-table";
import { useCallback, useMemo } from "react";

import type {
  ListLayoutRead,
  ListLayoutReadKind,
  SortField,
  TaskStatusRead,
} from "@/api/generated/initiativeAPI.schemas";
import { type PersistedTableState, usePersistedTableState } from "@/hooks/usePersistedTableState";
import { useProjectTaskStatuses } from "@/hooks/useProjects";
import { useTags } from "@/hooks/useTags";
import { listLayouts, useProjectLayouts } from "@/hooks/useToolLayouts";
import { useViewPreference } from "@/hooks/useViewPreference";
import {
  EMPTY_TASK_FILTERS,
  type StoredTaskFilters,
  specFromStored,
  type TaskFilterSpec,
  taskFilterCount,
  taskSortFields,
} from "@/lib/filters/taskFilters";
import { type Preset, presetsOf } from "@/lib/layouts/presets";

/** Where one person's view of a project is kept. */
export const projectViewsPreferenceKey = (projectId: number) => `project:${projectId}:views`;

/** What one person keeps for a project: the layout they were last in, and their
 *  own filters and sort for each layout they changed, by its kind. */
export interface StoredView {
  layout: string | null;
  filters: Record<string, TaskFilterSpec>;
  sorting: Record<string, SortingState>;
}

const EMPTY_VIEW: StoredView = { layout: null, filters: {}, sorting: {} };
const EMPTY_SORTING: SortingState = [];

const isSorting = (raw: unknown): raw is SortingState =>
  Array.isArray(raw) &&
  raw.every(
    (each) =>
      each !== null &&
      typeof each === "object" &&
      typeof (each as { id?: unknown }).id === "string" &&
      typeof (each as { desc?: unknown }).desc === "boolean"
  );

/**
 * Coerce whatever comes back from the server into this person's view, or null
 * when nothing is stored. Drops anything with the wrong type, so a stale or
 * corrupted blob can't crash the UI. What an older release kept (`view`, the
 * view it named) is read as the layout of that name.
 */
export function sanitizeStoredView(raw: unknown): StoredView | null {
  if (raw === null || typeof raw !== "object") return null;
  const parsed = raw as { layout?: unknown; view?: unknown; filters?: unknown; sorting?: unknown };
  const filters: Record<string, TaskFilterSpec> = {};
  if (parsed.filters !== null && typeof parsed.filters === "object") {
    for (const [kind, spec] of Object.entries(parsed.filters)) {
      if (spec !== null && typeof spec === "object") {
        filters[kind] = specFromStored(spec as StoredTaskFilters);
      }
    }
  }
  const sorting: Record<string, SortingState> = {};
  if (parsed.sorting !== null && typeof parsed.sorting === "object") {
    for (const [kind, sort] of Object.entries(parsed.sorting)) {
      if (isSorting(sort)) sorting[kind] = sort;
    }
  }
  const layout = parsed.layout ?? parsed.view;
  return { layout: typeof layout === "string" ? layout : null, filters, sorting };
}

/** What the URL names: `?layout=` and `?preset=`, which a link means for
 *  whoever opens it. */
export type ProjectViewSearch = { layout?: string; preset?: string };

/**
 * Which layout a person sees and their filters and sort for it: the layout the
 * URL names (a link means the same layout for whoever opens it), else the one
 * they were last in, else the one the project opens on. A preset the URL names
 * gives its filters and sort; otherwise they are the person's own. The page
 * and the route's prefetch both resolve it here, so the prefetch lands on the
 * key the page asks for.
 */
export const resolveProjectView = (
  search: ProjectViewSearch,
  layouts: readonly ListLayoutRead[],
  stored: StoredView | null
) => {
  const layout =
    layouts.find((each) => each.kind === search.layout) ??
    layouts.find((each) => each.kind === stored?.layout) ??
    layouts.find((each) => each.is_default) ??
    layouts[0] ??
    null;
  const kind: ListLayoutReadKind = layout?.kind ?? "table";
  const presets = presetsOf(layout?.definition);
  const preset = presets.find((each) => each.slug === search.preset) ?? null;
  return {
    layout,
    kind,
    presets,
    preset,
    spec: preset?.spec ?? stored?.filters[kind] ?? EMPTY_TASK_FILTERS,
    sorting: preset?.sorting ?? stored?.sorting[kind] ?? EMPTY_SORTING,
  };
};

/** `record` without `key`. */
const without = <T>(record: Record<string, T>, key: string): Record<string, T> =>
  Object.fromEntries(Object.entries(record).filter(([each]) => each !== key));

export function useProjectTaskView({
  projectId,
  taskStatuses,
  search,
}: {
  projectId: number;
  /** The project's statuses, to drop a filter on one that is gone. */
  taskStatuses: TaskStatusRead[];
  search: ProjectViewSearch;
}) {
  const [storedRaw, setStored, { isLoaded: filtersLoaded }] = useViewPreference<unknown>(
    projectViewsPreferenceKey(projectId),
    null
  );
  const stored = useMemo(() => sanitizeStoredView(storedRaw), [storedRaw]);

  // The project's layouts. `can_configure` is computed server-side and is what
  // gates the editor. The list waits for them, which say how it is drawn; a
  // set that cannot be read is reported, with a way to ask again, rather than
  // guessed at.
  const layoutsQuery = useProjectLayouts(projectId);
  const layoutsLoaded = layoutsQuery.data !== undefined;
  const layoutsFailed = layoutsQuery.isError && !layoutsLoaded;
  const { refetch: refetchLayouts } = layoutsQuery;
  const retryLayouts = useCallback(() => void refetchLayouts(), [refetchLayouts]);
  const canConfigure = layoutsQuery.data?.can_configure ?? false;
  const layouts = useMemo(() => listLayouts(layoutsQuery.data), [layoutsQuery.data]);

  const { layout, kind, presets, preset, spec, sorting } = useMemo(
    () => resolveProjectView(search, layouts, filtersLoaded ? stored : null),
    [search, layouts, stored, filtersLoaded]
  );

  const writeStored = useCallback(
    (patch: (current: StoredView) => StoredView) =>
      setStored((prev: unknown) => patch(sanitizeStoredView(prev) ?? EMPTY_VIEW)),
    [setStored]
  );

  /** Keep `next` as this person's filters for the layout on screen, or drop
   *  theirs (null) to see every task. */
  const setFilters = useCallback(
    (next: TaskFilterSpec | null) =>
      writeStored((view) => ({
        ...view,
        layout: kind,
        filters: next ? { ...view.filters, [kind]: next } : without(view.filters, kind),
      })),
    [kind, writeStored]
  );

  /** Keep `next` as this person's sort for the layout on screen. */
  const setSorting = useCallback(
    (next: SortingState) =>
      writeStored((view) => ({
        ...view,
        layout: kind,
        sorting: next.length ? { ...view.sorting, [kind]: next } : without(view.sorting, kind),
      })),
    [kind, writeStored]
  );

  /** Make `preset`'s filters and sort this person's own for the layout on
   *  screen. */
  const applyPreset = useCallback(
    (next: Preset) =>
      writeStored((view) => ({
        ...view,
        layout: kind,
        filters: { ...view.filters, [kind]: next.spec },
        sorting: next.sorting.length
          ? { ...view.sorting, [kind]: next.sorting }
          : without(view.sorting, kind),
      })),
    [kind, writeStored]
  );

  /** Make `next` the layout this person comes back to. */
  const rememberLayout = useCallback(
    (next: ListLayoutReadKind) => writeStored((view) => ({ ...view, layout: next })),
    [writeStored]
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
   * Pruning is derived rather than written back: rewriting someone's filters
   * on their behalf is not this component's call. Editing any filter persists
   * the pruned set, so it heals on the first change.
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
    layoutsLoaded,
    layoutsFailed,
    retryLayouts,
    retryingLayouts: layoutsQuery.isFetching,
    layouts,
    canConfigure,
    layout,
    kind,
    /** What the layout on screen offers to start from. */
    presets,
    /** The one the URL names, while it does. */
    preset,
    spec,
    /** This person narrows the list on screen. */
    filtered: taskFilterCount(spec) > 0,
    appliedSpec,
    sorting,
    setFilters,
    setSorting,
    applyPreset,
    rememberLayout,
  };
}

export const projectTaskTableKey = (projectId: number, kind: string) =>
  `initiative-project-${projectId}-${kind}-task-table`;

/** How a project's task table is shown to one person: grouped as they left it
 *  on this device, and sorted as their view keeps it. */
export type ProjectTaskTableState = [
  PersistedTableState,
  {
    setGrouping: (next: PersistedTableState["grouping"]) => void;
    setSorting: (next: SortingState) => void;
  },
];

export const useProjectTaskTableState = (
  projectId: number,
  kind: string,
  sorting: SortingState,
  setSorting: (next: SortingState) => void
): ProjectTaskTableState => {
  const [{ grouping }, { setGrouping }] = usePersistedTableState(
    projectTaskTableKey(projectId, kind)
  );
  return useMemo(
    () => [
      { grouping, sorting },
      { setGrouping, setSorting },
    ],
    [grouping, sorting, setGrouping, setSorting]
  );
};

/** The order a list shows tasks in, as the endpoint's `sorting`: the table's
 *  sort while it is the layout, and the project's order in every other. */
export const taskViewSorting = (
  kind: ListLayoutReadKind,
  tableSorting: Parameters<typeof taskSortFields>[0]
): SortField[] => (kind === "table" ? taskSortFields(tableSorting) : []);

/** What an export of the project starts from for this person: the tasks and
 *  the order their view of it shows, with the statuses those filters name. */
export function useProjectTaskExportView(projectId: number) {
  const taskStatuses = useProjectTaskStatuses(projectId).data ?? EMPTY_STATUSES;
  const { appliedSpec, kind, sorting } = useProjectTaskView({
    projectId,
    taskStatuses,
    search: NO_SEARCH,
  });
  return useMemo(
    () => ({ tasks: appliedSpec, taskSorting: taskViewSorting(kind, sorting), taskStatuses }),
    [appliedSpec, kind, sorting, taskStatuses]
  );
}

const EMPTY_STATUSES: TaskStatusRead[] = [];
const NO_SEARCH = {};
