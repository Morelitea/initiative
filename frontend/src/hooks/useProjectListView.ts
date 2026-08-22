import { useCallback, useEffect, useMemo, useState } from "react";

import type { ProjectRead, TagRead, TagSummary } from "@/api/generated/initiativeAPI.schemas";
import { useTags } from "@/hooks/useTags";
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
  /** The raw list for this tab — active, template, or archived projects. */
  projects: ProjectRead[];
  /** View-preference namespace, e.g. `project:list` or `project:archive`. */
  storagePrefix: string;
  /**
   * Manual drag-and-drop order. Only the active list can be reordered, so the
   * other tabs hide the option and fall back to "recently updated".
   */
  allowCustomSort?: boolean;
  /** Pull pinned projects into their own section above the list. */
  separatePinned?: boolean;
  /** Locks the tag filter (the cross-initiative tag browse). */
  fixedTagIds?: number[];
  /** Initiatives whose projects the viewer may see; others are dropped. */
  viewableInitiativeIds?: Set<number> | null;
};

/**
 * Search / tag / favorite filtering, sorting, and the persisted view state
 * behind a project listing. Every projects tab runs the same pipeline through
 * this hook so their filters behave identically and only their data differs.
 */
export const useProjectListView = ({
  projects,
  storagePrefix,
  allowCustomSort = false,
  separatePinned = false,
  fixedTagIds,
  viewableInitiativeIds,
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

  const tagFilters = fixedTagIds
    ? fixedTagIds
    : Array.isArray(persistedTagFilters)
      ? persistedTagFilters.filter((n): n is number => typeof n === "number" && Number.isFinite(n))
      : [];
  const setTagFilters = useCallback(
    (next: number[]) => {
      if (fixedTagIds) return;
      setPersistedTagFilters(next);
    },
    [fixedTagIds, setPersistedTagFilters]
  );

  const { data: allTags = [] } = useTags();
  const selectedTagsForFilter = useMemo(() => {
    const tagMap = new Map(allTags.map((tag) => [tag.id, tag]));
    return tagFilters
      .map((id) => tagMap.get(id))
      .filter((tag): tag is TagRead => tag !== undefined);
  }, [allTags, tagFilters]);

  const handleTagFiltersChange = useCallback(
    (nextTags: TagSummary[]) => setTagFilters(nextTags.map((tag) => tag.id)),
    [setTagFilters]
  );

  // What the filter button reports while the panel is closed. Sort order is
  // deliberately excluded — it reorders the list, it doesn't narrow it, so
  // counting it would badge a list that is showing everything.
  const activeFilterCount =
    (searchQuery.trim() ? 1 : 0) + (fixedTagIds ? 0 : tagFilters.length) + (favoritesOnly ? 1 : 0);

  const clearFilters = useCallback(() => {
    setSearchQuery("");
    setTagFilters([]);
    setFavoritesOnly(false);
  }, [setSearchQuery, setTagFilters]);

  const filteredProjects = useMemo(() => {
    const query = searchQuery.trim().toLowerCase();
    const tagFilterSet = new Set(tagFilters);
    return projects.filter((project) => {
      const projectInitiativeId = project.initiative?.id ?? project.initiative_id ?? null;
      if (
        viewableInitiativeIds &&
        projectInitiativeId !== null &&
        !viewableInitiativeIds.has(projectInitiativeId)
      ) {
        return false;
      }
      const matchesSearch = !query ? true : project.name.toLowerCase().includes(query);
      const matchesFavorites = !favoritesOnly ? true : Boolean(project.is_favorited);
      const matchesTags =
        tagFilterSet.size === 0 || (project.tags?.some((tag) => tagFilterSet.has(tag.id)) ?? false);
      return matchesSearch && matchesFavorites && matchesTags;
    });
  }, [projects, searchQuery, favoritesOnly, tagFilters, viewableInitiativeIds]);

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
      searchQuery,
      onSearchQueryChange: setSearchQuery,
      filtersOpen,
      onFiltersOpenChange: setFiltersOpen,
      sortMode,
      onSortModeChange: setSortMode,
      favoritesOnly,
      onFavoritesOnlyChange: setFavoritesOnly,
      tagFilters: selectedTagsForFilter,
      onTagFiltersChange: handleTagFiltersChange,
      fixedTagIds,
      allowCustomSort,
      onClear: clearFilters,
      activeCount: activeFilterCount,
    },
  };
};
