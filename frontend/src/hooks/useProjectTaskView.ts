/**
 * One person's view of a project's tasks: which of the project's list layouts
 * they are in, and their own filters, sort and grouping on each, kept for them
 * on the project as their view of that list ({@link useListView}). A layout is
 * how the project draws its tasks; what a person narrows the list to and how
 * they order it are theirs. A layout's presets are where they can start from:
 * picking one makes its filters and sort theirs.
 *
 * The project page reads it to show the list, and the project's export card
 * reads it so an export starts from the same tasks.
 */

import type { GroupingState, SortingState } from "@tanstack/react-table";
import { useCallback, useMemo } from "react";

import type {
  ListLayoutRead,
  ListLayoutReadKind,
  SortField,
  TaskStatusRead,
} from "@/api/generated/initiativeAPI.schemas";
import { CALENDAR_VIEW_MODE_KEY } from "@/components/calendar";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import {
  deviceJSON,
  type ListViewSpec,
  NO_PART_VIEW,
  partOf,
  type StoredListView,
  useListView,
  usePresetLink,
  viewKey,
} from "@/hooks/useListView";
import { useProjectTaskStatuses } from "@/hooks/useProjects";
import { useTags } from "@/hooks/useTags";
import { listLayouts, useProjectLayouts } from "@/hooks/useToolLayouts";
import {
  EMPTY_TASK_FILTERS,
  type StoredTaskFilters,
  specFromStored,
  type TaskFilterSpec,
  taskFilterCount,
  taskFiltersEqual,
  taskSortFields,
} from "@/lib/filters/taskFilters";
import { type Preset, presetsOf, TASK_PRESETS } from "@/lib/layouts/presets";

const readTaskFilters = (raw: unknown) => specFromStored(raw as StoredTaskFilters);
const TASK_DEFAULTS = { filters: EMPTY_TASK_FILTERS, ...NO_PART_VIEW };

/** What an older release kept for a project: its view under the project's id
 *  alone (`layout` or `view`, then filters and sort by layout), each layout's
 *  table grouping on the device, and the calendar's month or week, which was
 *  the same on every calendar. */
const carryProjectView = (
  items: Readonly<Record<string, unknown>>,
  projectId: number
): StoredListView | null => {
  const old = (items[`project:${projectId}:views`] ?? {}) as {
    layout?: unknown;
    view?: unknown;
    filters?: Record<string, unknown>;
    sorting?: Record<string, unknown>;
  };
  const parts: NonNullable<StoredListView["parts"]> = {};
  for (const kind of ["table", "board", "calendar"]) {
    const grouping = (
      deviceJSON(`initiative-project-${projectId}-${kind}-task-table`) as {
        grouping?: unknown;
      } | null
    )?.grouping;
    const entry = {
      ...(old.filters?.[kind] !== undefined ? { filters: old.filters[kind] } : {}),
      ...(old.sorting?.[kind] !== undefined ? { sorting: old.sorting[kind] } : {}),
      ...(Array.isArray(grouping) ? { grouping } : {}),
    };
    if (Object.keys(entry).length > 0) parts[kind] = entry;
  }
  const layout = old.layout ?? old.view;
  const mode = items[CALENDAR_VIEW_MODE_KEY];
  if (Object.keys(parts).length === 0 && typeof layout !== "string" && typeof mode !== "string") {
    return null;
  }
  return {
    layout: typeof layout === "string" ? layout : null,
    mode: typeof mode === "string" ? mode : null,
    parts,
  };
};

/** Where one person's view of a project's tasks is kept, and what it holds. */
export const projectViewSpec = (
  communityId: number,
  projectId: number
): ListViewSpec<TaskFilterSpec> => ({
  key: viewKey(communityId, "project", projectId),
  read: readTaskFilters,
  defaults: TASK_DEFAULTS,
  carryOver: (items) => carryProjectView(items, projectId),
});

/** What the URL names: `?layout=` and `?preset=`, which a link means for
 *  whoever opens it. */
export type ProjectViewSearch = { layout?: string; preset?: string };

/** The layout a person sees: the one the URL names (a link means the same
 *  layout for whoever opens it), else the one they were last in, else the one
 *  the project opens on. */
const layoutShown = (
  search: ProjectViewSearch,
  layouts: readonly ListLayoutRead[],
  view: StoredListView
) =>
  layouts.find((each) => each.kind === search.layout) ??
  layouts.find((each) => each.kind === view.layout) ??
  layouts.find((each) => each.is_default) ??
  layouts[0] ??
  null;

/**
 * Which layout a person sees and their filters and sort for it. A preset the
 * URL names gives its filters and sort; otherwise they are the person's own.
 * The page and the route's prefetch both resolve it here, so the prefetch
 * lands on the key the page asks for.
 */
export const resolveProjectView = (
  search: ProjectViewSearch,
  layouts: readonly ListLayoutRead[],
  view: StoredListView
) => {
  const layout = layoutShown(search, layouts, view);
  const kind: ListLayoutReadKind = layout?.kind ?? "table";
  const presets = presetsOf(layout?.definition, TASK_PRESETS);
  const preset = presets.find((each) => each.slug === search.preset) ?? null;
  const own = partOf(view, kind, { read: readTaskFilters, defaults: TASK_DEFAULTS });
  return {
    layout,
    kind,
    presets,
    preset,
    spec: preset?.filters ?? own.filters,
    sorting: preset?.sorting ?? own.sorting,
  };
};

const sameSorting = (a: SortingState, b: SortingState) =>
  a.length === b.length &&
  a.every((each, index) => each.id === b[index].id && each.desc === b[index].desc);

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
  const communityId = useActiveCommunityId();
  const spec = useMemo(() => projectViewSpec(communityId, projectId), [communityId, projectId]);

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

  const view = useListView(spec, (kept) => layoutShown(search, layouts, kept)?.kind ?? "table");
  const kind = view.part as ListLayoutReadKind;
  const layout = layouts.find((each) => each.kind === kind) ?? null;
  const presets = useMemo(() => presetsOf(layout?.definition, TASK_PRESETS), [layout]);

  const { apply, setFilters: keepFilters, setSorting, rememberLayout } = view;
  /** Keep `next` as this person's filters for the layout on screen, or drop
   *  theirs (null) to see every task. */
  const setFilters = useCallback(
    (next: TaskFilterSpec | null) => {
      keepFilters(next);
      rememberLayout(kind);
    },
    [keepFilters, rememberLayout, kind]
  );
  const keepSorting = useCallback(
    (next: SortingState) => {
      setSorting(next);
      rememberLayout(kind);
    },
    [setSorting, rememberLayout, kind]
  );
  const applyPreset = useCallback(
    (next: Preset) => apply({ filters: next.filters, sorting: next.sorting }),
    [apply]
  );
  const { preset, pick: pickPreset } = usePresetLink({
    slug: search.preset,
    presets,
    ready: layoutsLoaded && view.loaded,
    scope: `${projectId}:${kind}`,
    apply: applyPreset,
    same: useCallback(
      (each: Preset) =>
        taskFiltersEqual(view.filters, each.filters) && sameSorting(view.sorting, each.sorting),
      [view.filters, view.sorting]
    ),
  });
  const spec_ = preset?.filters ?? view.filters;
  const sorting = preset?.sorting ?? view.sorting;

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
    const spec = spec_;
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
  }, [spec_, tags, tagsLoaded, tagsFailed, taskStatuses]);

  return {
    filtersLoaded: view.loaded,
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
    spec: spec_,
    /** This person narrows the list on screen. */
    filtered: taskFilterCount(spec_) > 0,
    appliedSpec,
    sorting,
    setFilters,
    setSorting: keepSorting,
    /** Name a preset in the URL, which applies it; or none. */
    pickPreset,
    rememberLayout,
    /** How they show the calendar: month, week, day or a list. */
    mode: view.mode,
    setMode: view.setMode,
    grouping: view.grouping,
    setGrouping: view.setGrouping,
  };
}

/** How a project's task table is shown to one person: grouped and sorted as
 *  their view keeps it. */
export type ProjectTaskTableState = [
  { grouping: GroupingState; sorting: SortingState },
  {
    setGrouping: (next: GroupingState) => void;
    setSorting: (next: SortingState) => void;
  },
];

export const useProjectTaskTableState = (
  grouping: GroupingState,
  setGrouping: (next: GroupingState) => void,
  sorting: SortingState,
  setSorting: (next: SortingState) => void
): ProjectTaskTableState =>
  useMemo(
    () => [
      { grouping, sorting },
      { setGrouping, setSorting },
    ],
    [grouping, sorting, setGrouping, setSorting]
  );

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
