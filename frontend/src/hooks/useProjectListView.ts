import { keepPreviousData } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useState } from "react";

import type {
  ListProjectsApiV1CGuildIdProjectsGetParams,
  Tool,
} from "@/api/generated/initiativeAPI.schemas";
import type { ToolListFilters } from "@/components/tools/ToolFilterFields";
import { useDebouncedValue } from "@/hooks/useDebouncedValue";
import { useProjects } from "@/hooks/useProjects";
import { useViewPreference } from "@/hooks/useViewPreference";

export type ProjectSortMode = "custom" | "updated" | "created" | "alphabetical" | "recently_viewed";

const SORT_MODES: ProjectSortMode[] = [
  "custom",
  "updated",
  "created",
  "alphabetical",
  "recently_viewed",
];

type UseProjectListViewOptions = {
  /** Which list this tab reads — its initiative, and active, template, or
   *  archived projects. The search and tags are added here. */
  params: ListProjectsApiV1CGuildIdProjectsGetParams;
  /** View-preference namespace, e.g. `project:list` or `project:archive`. */
  storagePrefix: string;
  /**
   * Manual drag-and-drop order. Only the active list can be reordered, so the
   * other tabs hide the option and fall back to "recently updated".
   */
  allowCustomSort?: boolean;
  /** Pull pinned projects into their own section above the list. */
  separatePinned?: boolean;
};

/**
 * The list behind a project listing: read with its search and tags, then
 * narrowed to favourites and sorted here, with the persisted view state. Every
 * projects tab runs the same pipeline through this hook so their filters
 * behave identically and only their data differs.
 */
export const useProjectListView = ({
  params,
  storagePrefix,
  allowCustomSort = false,
  separatePinned = false,
}: UseProjectListViewOptions) => {
  const defaultSortMode: ProjectSortMode = allowCustomSort ? "custom" : "updated";

  const [searchQuery, setSearchQuery] = useViewPreference<string>(`${storagePrefix}:search`, "");
  const [persistedSortMode, setPersistedSortMode] = useViewPreference<ProjectSortMode>(
    `${storagePrefix}:sort`,
    defaultSortMode
  );
  const [persistedViewMode, setPersistedViewMode] = useViewPreference<string>(
    `${storagePrefix}:view-mode`,
    "grid"
  );
  const [persistedTagFilters, setPersistedTagFilters] = useViewPreference<number[]>(
    `${storagePrefix}:tag-filters`,
    []
  );

  const [favoritesOnly, setFavoritesOnly] = useState(false);
  const [customOrder, setCustomOrder] = useState<number[]>([]);
  // Closed until asked for. The filter button carries a count of what's set, so
  // a narrowed list still says so with the panel shut — and the fields no
  // longer take the top of the page before the list itself.
  const [filtersOpen, setFiltersOpen] = useState(false);

  const sortMode: ProjectSortMode = SORT_MODES.includes(persistedSortMode)
    ? persistedSortMode === "custom" && !allowCustomSort
      ? defaultSortMode
      : persistedSortMode
    : defaultSortMode;
  const setSortMode = useCallback(
    (next: ProjectSortMode) => setPersistedSortMode(next),
    [setPersistedSortMode]
  );

  const viewMode: "grid" | "list" =
    persistedViewMode === "list" || persistedViewMode === "grid" ? persistedViewMode : "grid";
  const setViewMode = useCallback(
    (next: "grid" | "list") => setPersistedViewMode(next),
    [setPersistedViewMode]
  );

  const tagFilters = Array.isArray(persistedTagFilters)
    ? persistedTagFilters.filter((n): n is number => typeof n === "number" && Number.isFinite(n))
    : [];
  const setTagFilters = useCallback(
    (next: number[]) => {
      setPersistedTagFilters(next);
    },
    [setPersistedTagFilters]
  );

  const search = useDebouncedValue(searchQuery, 300).trim();
  const query = useProjects(
    {
      ...params,
      ...(search ? { search } : {}),
      ...(tagFilters.length > 0 ? { tag_ids: tagFilters } : {}),
    },
    // The cards stay on screen while a changed search is in flight.
    { placeholderData: keepPreviousData }
  );
  const projects = useMemo(() => query.data?.items ?? [], [query.data]);

  // The search and the tags are both saved preferences, so the filter fields'
  // answer writes back only what changed (the fields hand back this render's
  // values for everything they didn't touch).
  const filterValue: ToolListFilters<typeof Tool.project> = {
    search: searchQuery,
    tag_ids: tagFilters,
  };
  const handleFilterChange = (next: ToolListFilters<typeof Tool.project>) => {
    if (next.search !== filterValue.search) setSearchQuery(next.search ?? "");
    if (next.tag_ids !== filterValue.tag_ids) setTagFilters(next.tag_ids ?? []);
  };

  // What the filter button reports while the panel is closed. Sort order is
  // deliberately excluded — it reorders the list, it doesn't narrow it, so
  // counting it would badge a list that is showing everything.
  const activeFilterCount =
    (searchQuery.trim() ? 1 : 0) + tagFilters.length + (favoritesOnly ? 1 : 0);

  const clearFilters = useCallback(() => {
    setSearchQuery("");
    setTagFilters([]);
    setFavoritesOnly(false);
  }, [setSearchQuery, setTagFilters]);

  // Favourites are the reader's own, so they narrow here rather than on the
  // server, which has already left out what the reader cannot see.
  const filteredProjects = useMemo(
    () => (favoritesOnly ? projects.filter((project) => project.is_favorited) : projects),
    [projects, favoritesOnly]
  );

  const pinnedProjects = useMemo(() => {
    if (!separatePinned) return [];
    return filteredProjects
      .filter((project) => Boolean(project.pinned_at))
      .sort((a, b) => {
        const aPinned = a.pinned_at ? new Date(a.pinned_at).getTime() : 0;
        const bPinned = b.pinned_at ? new Date(b.pinned_at).getTime() : 0;
        if (aPinned === bPinned) {
          return new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime();
        }
        return bPinned - aPinned;
      });
  }, [filteredProjects, separatePinned]);

  const unpinnedProjects = useMemo(
    () =>
      separatePinned ? filteredProjects.filter((project) => !project.pinned_at) : filteredProjects,
    [filteredProjects, separatePinned]
  );

  // The manual order only covers projects that can be dragged; recompute it
  // whenever the underlying list changes so new projects land at the end.
  useEffect(() => {
    if (!allowCustomSort) return;
    const reorderable = projects.filter((project) => !separatePinned || !project.pinned_at);
    if (reorderable.length === 0) {
      setCustomOrder((prev) => (prev.length ? [] : prev));
      return;
    }
    const projectIds = reorderable.map((project) => project.id);
    setCustomOrder((prev) => {
      if (
        prev.length === projectIds.length &&
        prev.every((id, index) => id === projectIds[index])
      ) {
        return prev;
      }
      return projectIds;
    });
  }, [projects, allowCustomSort, separatePinned]);

  const sortedProjects = useMemo(() => {
    const next = [...unpinnedProjects];
    if (sortMode === "alphabetical") {
      next.sort((a, b) => a.name.localeCompare(b.name));
    } else if (sortMode === "created") {
      next.sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime());
    } else if (sortMode === "updated") {
      next.sort((a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime());
    } else if (sortMode === "recently_viewed") {
      next.sort((a, b) => {
        const aViewed = a.last_viewed_at ? new Date(a.last_viewed_at).getTime() : 0;
        const bViewed = b.last_viewed_at ? new Date(b.last_viewed_at).getTime() : 0;
        if (aViewed === bViewed) {
          return new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime();
        }
        return bViewed - aViewed;
      });
    } else {
      const orderMap = new Map<number, number>();
      customOrder.forEach((id, index) => {
        orderMap.set(id, index);
      });
      next.sort((a, b) => {
        const aIndex = orderMap.has(a.id) ? orderMap.get(a.id)! : Number.MAX_SAFE_INTEGER;
        const bIndex = orderMap.has(b.id) ? orderMap.get(b.id)! : Number.MAX_SAFE_INTEGER;
        return aIndex - bIndex;
      });
    }
    return next;
  }, [unpinnedProjects, sortMode, customOrder]);

  return {
    isLoading: query.isLoading,
    isError: query.isError,
    /** The list shows only some of the projects a manual order covers:
     *  narrowed by the server's search or tags, or to favourites. */
    narrowed: Boolean(search) || tagFilters.length > 0 || favoritesOnly,
    filteredProjects,
    pinnedProjects,
    sortedProjects,
    sortMode,
    viewMode,
    setViewMode,
    customOrder,
    setCustomOrder,
    filtersOpen,
    setFiltersOpen,
    activeFilterCount,
    /** Spread straight into `<ProjectsFilterBar />`. */
    filterBarProps: {
      value: filterValue,
      onChange: handleFilterChange,
      filtersOpen,
      onFiltersOpenChange: setFiltersOpen,
      sortMode,
      onSortModeChange: setSortMode,
      favoritesOnly,
      onFavoritesOnlyChange: setFavoritesOnly,
      allowCustomSort,
      onClear: clearFilters,
      activeCount: activeFilterCount,
    },
  };
};
