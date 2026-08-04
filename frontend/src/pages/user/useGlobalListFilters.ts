/**
 * Shared filter/sort persistence for the cross-guild "My" list pages
 * (projects, documents). These pages diverge on their columns, query hooks,
 * and i18n keys, but share this exact guild-filter + sort preference plumbing
 * verbatim — extracting it keeps the two sanitizers from drifting apart.
 */

import type { SortingState } from "@tanstack/react-table";
import { useCallback, useMemo } from "react";

import { useViewPreference } from "@/hooks/useViewPreference";

export type StoredPrefs = {
  guildFilters: number[];
  sortBy: string | undefined;
  sortDir: string | undefined;
};

export const FILTER_DEFAULTS: StoredPrefs = {
  guildFilters: [],
  sortBy: undefined,
  sortDir: undefined,
};

export const sanitizeStoredPrefs = (raw: unknown): StoredPrefs => {
  if (raw === null || typeof raw !== "object") return FILTER_DEFAULTS;
  const v = raw as Partial<StoredPrefs>;
  return {
    guildFilters: Array.isArray(v.guildFilters)
      ? v.guildFilters.filter((x): x is number => typeof x === "number")
      : [],
    sortBy: typeof v.sortBy === "string" ? v.sortBy : undefined,
    sortDir: typeof v.sortDir === "string" ? v.sortDir : undefined,
  };
};

/**
 * Persists the guild filter + sort selection under `storageKey` and adapts
 * DataTable sorting to the backend field names via `sortFieldMap`
 * (DataTable column ID → backend sort field).
 */
export function useGlobalListFilters(storageKey: string, sortFieldMap: Record<string, string>) {
  const [storedPrefsRaw, setStoredPrefs] = useViewPreference<StoredPrefs>(
    storageKey,
    FILTER_DEFAULTS
  );
  const storedPrefs = useMemo(() => sanitizeStoredPrefs(storedPrefsRaw), [storedPrefsRaw]);
  const { guildFilters, sortBy, sortDir } = storedPrefs;

  const setGuildFilters = useCallback(
    (next: number[] | ((prev: number[]) => number[])) =>
      setStoredPrefs((prev) => {
        const safe = sanitizeStoredPrefs(prev);
        return {
          ...safe,
          guildFilters: typeof next === "function" ? next(safe.guildFilters) : next,
        };
      }),
    [setStoredPrefs]
  );
  const setSortBy = useCallback(
    (next: string | undefined) =>
      setStoredPrefs((prev) => ({ ...sanitizeStoredPrefs(prev), sortBy: next })),
    [setStoredPrefs]
  );
  const setSortDir = useCallback(
    (next: string | undefined) =>
      setStoredPrefs((prev) => ({ ...sanitizeStoredPrefs(prev), sortDir: next })),
    [setStoredPrefs]
  );

  const handleSortingChange = useCallback(
    (sorting: SortingState) => {
      if (sorting.length > 0) {
        const field = sortFieldMap[sorting[0].id];
        if (field) {
          setSortBy(field);
          setSortDir(sorting[0].desc ? "desc" : "asc");
        }
      } else {
        setSortBy(undefined);
        setSortDir(undefined);
      }
    },
    [sortFieldMap, setSortDir, setSortBy]
  );

  const initialSorting = useMemo(() => {
    if (!sortBy) return undefined;
    const reverse = Object.fromEntries(
      Object.entries(sortFieldMap).map(([col, field]) => [field, col])
    );
    const colId = reverse[sortBy];
    if (!colId) return undefined;
    return [{ id: colId, desc: sortDir === "desc" }];
  }, [sortFieldMap, sortDir, sortBy]);

  return { guildFilters, sortBy, sortDir, setGuildFilters, handleSortingChange, initialSorting };
}
