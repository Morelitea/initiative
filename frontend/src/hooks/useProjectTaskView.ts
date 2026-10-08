/**
 * One person's view of a project's tasks: the filters they left it on, the
 * view they were in, and the preset those filters came from, ranked against
 * the URL and the project's default preset.
 *
 * The project page reads it to show the list, and the project's export card
 * reads it so an export starts from the same tasks.
 */

import { useCallback, useMemo } from "react";

import type {
  TaskFilterSpec as ApiTaskFilterSpec,
  SortField,
  TaskStatusRead,
} from "@/api/generated/initiativeAPI.schemas";
import type { PropertyFilterCondition } from "@/components/properties/PropertyFilter";
import { useFilterPresets } from "@/hooks/useFilterPresets";
import { usePersistedTableState } from "@/hooks/usePersistedTableState";
import { useProjectTaskStatuses } from "@/hooks/useProjects";
import { useTags } from "@/hooks/useTags";
import { useViewPreference } from "@/hooks/useViewPreference";
import { resolvePresetState } from "@/lib/filters/presets";
import {
  EMPTY_TASK_FILTERS,
  specFromApi,
  TASK_VIEW_MODES,
  type TaskFilterSpec,
  type TaskViewMode,
  taskFiltersEqual,
  taskSortFields,
} from "@/lib/filters/taskFilters";

type ViewMode = TaskViewMode;

/**
 * What this project's task view remembers for one person: the filter values,
 * which view they were in, and which preset (if any) those filters came from.
 *
 * The filter half IS {@link TaskFilterSpec} — the same object a saved preset
 * holds and the same one the URL names — so a preset can be applied, tweaked,
 * and saved back without translating between shapes.
 */
export type StoredFilters = TaskFilterSpec & {
  viewMode: ViewMode;
  /** The preset these values came from, or null once they were tweaked. */
  activePresetSlug: string | null;
};

const DEFAULT_FILTERS: StoredFilters = {
  ...EMPTY_TASK_FILTERS,
  viewMode: "table",
  activePresetSlug: null,
};

/** The pre-preset key names, still on disk for anyone who has used the app.
 *  Read once and written back in the new shape, so nobody loses their filters. */
type LegacyStoredFilters = {
  assigneeFilters?: unknown;
  dueFilter?: unknown;
  statusFilters?: unknown;
  tagFilters?: unknown;
  propertyFilters?: unknown;
  showArchived?: unknown;
};

const numberList = (raw: unknown): number[] | undefined =>
  Array.isArray(raw) ? raw.filter((v): v is number => typeof v === "number") : undefined;

/**
 * Coerce whatever shape comes back from the server (or a legacy
 * localStorage blob) into a valid ``StoredFilters``. Drops any field
 * with the wrong type so a stale or corrupted blob can't crash the UI.
 */
function sanitizeStoredFilters(raw: unknown): StoredFilters {
  if (raw === null || typeof raw !== "object") return DEFAULT_FILTERS;
  const parsed = raw as Partial<StoredFilters> & LegacyStoredFilters;
  const out: StoredFilters = {
    ...DEFAULT_FILTERS,
    ...specFromApi(parsed as ApiTaskFilterSpec),
  };
  if (TASK_VIEW_MODES.includes(parsed.viewMode as ViewMode)) {
    out.viewMode = parsed.viewMode as ViewMode;
  }
  if (typeof parsed.activePresetSlug === "string") {
    out.activePresetSlug = parsed.activePresetSlug;
  }

  // Legacy key names, used only when the modern one is absent.
  if (parsed.assignees === undefined && Array.isArray(parsed.assigneeFilters)) {
    out.assignees = parsed.assigneeFilters.filter((v): v is string => typeof v === "string");
  }
  if (parsed.due === undefined && typeof parsed.dueFilter === "string") {
    out.due = parsed.dueFilter === "all" ? null : (parsed.dueFilter as StoredFilters["due"]);
  }
  if (parsed.status_ids === undefined) {
    out.status_ids = numberList(parsed.statusFilters) ?? out.status_ids;
  }
  if (parsed.tag_ids === undefined) {
    out.tag_ids = numberList(parsed.tagFilters) ?? out.tag_ids;
  }
  if (parsed.properties === undefined && Array.isArray(parsed.propertyFilters)) {
    out.properties = (parsed.propertyFilters as PropertyFilterCondition[]).filter(
      (entry) =>
        entry !== null && typeof entry === "object" && typeof entry.property_id === "number"
    );
  }
  if (parsed.include_archived === undefined && typeof parsed.showArchived === "boolean") {
    out.include_archived = parsed.showArchived;
  }
  return out;
}

export function useProjectTaskView({
  projectId,
  taskStatuses,
  defaultView,
  search,
}: {
  projectId: number;
  /** The project's statuses, to drop a filter on one that is gone. */
  taskStatuses: TaskStatusRead[];
  /** The project's configured default view, used only when this person has
   *  no view of their own yet and the URL doesn't name one. */
  defaultView?: string | null;
  /** What the URL names, which a link means for whoever opens it. */
  search: { preset?: string; view?: ViewMode };
}) {
  const filterStorageKey = `project:${projectId}:view-filters`;
  // `null` fallback on purpose: "nothing saved yet" has to stay distinguishable
  // from "saved, and happens to equal the defaults", or someone's first visit
  // would shadow the project's own default preset with an empty one.
  const [storedFilters, setStoredFilters, { isLoaded: filtersLoaded }] =
    useViewPreference<StoredFilters | null>(filterStorageKey, null);
  const stored = useMemo(
    () => (storedFilters ? sanitizeStoredFilters(storedFilters) : null),
    [storedFilters]
  );
  const patchFilters = useCallback(
    (patch: Partial<StoredFilters>) =>
      setStoredFilters((prev) => ({ ...sanitizeStoredFilters(prev), ...patch })),
    [setStoredFilters]
  );

  // The project's shared presets. `can_manage` is computed server-side — a
  // project manager, the project owner, or a community admin — and is what gates
  // every curation affordance.
  const presetsQuery = useFilterPresets(projectId);
  const presetsLoaded = presetsQuery.isSuccess;
  const canManagePresets = presetsQuery.data?.can_manage ?? false;
  const presets = useMemo(
    () =>
      (presetsQuery.data?.items ?? []).map((preset) => ({
        ...preset,
        filters: specFromApi(preset.filters),
      })),
    [presetsQuery.data]
  );

  // URL first (a link means the same thing for whoever opens it), then what
  // this person last had, then the project's default. See lib/filters/presets.
  const { spec, viewMode, activeSlug, modified, unresolvedPreset } = useMemo(
    () =>
      resolvePresetState<TaskFilterSpec, ViewMode>({
        search,
        presets,
        stored:
          filtersLoaded && stored
            ? {
                spec: stored,
                viewMode: stored.viewMode,
                activePresetSlug: stored.activePresetSlug,
              }
            : null,
        allowedViews: TASK_VIEW_MODES,
        defaultView,
        fallbackView: "table",
        emptySpec: EMPTY_TASK_FILTERS,
        equals: taskFiltersEqual,
      }),
    [search, presets, stored, filtersLoaded, defaultView]
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
   * from a shared preset, and rewriting that on someone's behalf (or marking
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
    patchFilters,
    presets,
    presetsLoaded,
    canManagePresets,
    spec,
    viewMode,
    activeSlug,
    modified,
    unresolvedPreset,
    appliedSpec,
  };
}

export const projectTaskTableKey = (projectId: number) =>
  `initiative-project-${projectId}-task-table`;

/** Which column one project's task table is grouped and sorted by, as the
 *  reader left it. Kept beside the table's column-visibility map so the whole
 *  "how this list is shown" answer survives a reload together. */
export const useProjectTaskTableState = (projectId: number) =>
  usePersistedTableState(projectTaskTableKey(projectId));

/** The order a view lists tasks in, as the endpoint's `sorting`: the table's
 *  own sort while it is the view, and the project's order in every other. */
export const taskViewSorting = (
  viewMode: ViewMode,
  tableSorting: Parameters<typeof taskSortFields>[0]
): SortField[] => (viewMode === "table" ? taskSortFields(tableSorting) : []);

/** What an export of the project starts from for this person: the tasks and
 *  the order their view of it shows, with the statuses those filters name. */
export function useProjectTaskExportView(projectId: number, defaultView?: string | null) {
  const taskStatuses = useProjectTaskStatuses(projectId).data ?? EMPTY_STATUSES;
  const { appliedSpec, viewMode } = useProjectTaskView({
    projectId,
    taskStatuses,
    defaultView,
    search: NO_SEARCH,
  });
  const [{ sorting }] = useProjectTaskTableState(projectId);
  return useMemo(
    () => ({ tasks: appliedSpec, taskSorting: taskViewSorting(viewMode, sorting), taskStatuses }),
    [appliedSpec, viewMode, sorting, taskStatuses]
  );
}

const EMPTY_STATUSES: TaskStatusRead[] = [];
const NO_SEARCH = {};
