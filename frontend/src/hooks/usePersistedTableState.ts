import type { GroupingState, SortingState } from "@tanstack/react-table";
import { useCallback, useRef, useState } from "react";

import { getItem, setItem } from "@/lib/storage";

/**
 * The parts of a DataTable's state that are the reader's own choices about how
 * a list is shown, rather than what it holds. Column visibility is the third
 * such choice and has its own hook ({@link usePersistedColumnVisibility}),
 * which predates this one and keeps its own storage key.
 */
export type PersistedTableState = {
  grouping: GroupingState;
  sorting: SortingState;
};

const EMPTY: PersistedTableState = { grouping: [], sorting: [] };

/**
 * DataTable ``grouping`` and ``sorting`` persisted to our @/lib/storage wrapper
 * (localStorage on web, Capacitor Preferences on native, always synchronous —
 * which is what lets the stored value seed the table on its very first render,
 * where DataTable captures `initialSorting`/`initialState.grouping`).
 *
 * Feed the returned state back as those two seeds and write to it from
 * ``onGroupingChange``/``onSortingChange``:
 *
 * ```tsx
 * const [tableState, { setGrouping, setSorting }] = usePersistedTableState(key);
 * <DataTable
 *   initialSorting={tableState.sorting}
 *   initialState={{ grouping: tableState.grouping }}
 *   onGroupingChange={setGrouping}
 *   onSortingChange={setSorting}
 * />
 * ```
 *
 * ``defaults`` cover the first visit only — once anything is stored, that blob
 * is the whole answer, so a reader who deliberately cleared the sorting gets an
 * unsorted table back rather than the default returning behind them.
 *
 * A table whose sorting is owned elsewhere (a server-persisted preference, say)
 * can use the grouping half alone and leave ``onSortingChange`` to that owner.
 *
 * Ids are stored as written. An id that no longer matches a column is simply
 * ignored by TanStack, and starts applying again if that column comes back —
 * so a column that loads late (a property definition, say) keeps its sort.
 */
export function usePersistedTableState(
  storageKey: string,
  defaults?: Partial<PersistedTableState>
): [
  PersistedTableState,
  { setGrouping: (next: GroupingState) => void; setSorting: (next: SortingState) => void },
] {
  // Captured once: a caller that rebuilds the object every render must not
  // reset a table that has since been stored.
  const defaultsRef = useRef(defaults);
  const [state, setState] = useState<PersistedTableState>(() =>
    readStored(storageKey, defaultsRef.current)
  );
  // A list that swaps which thing it is showing (one project to the next)
  // swaps storage keys without remounting, and must not carry the previous
  // one's answer over. Re-read during render rather than in an effect, so the
  // first render under the new key already has the right seed.
  const [activeKey, setActiveKey] = useState(storageKey);
  if (activeKey !== storageKey) {
    setActiveKey(storageKey);
    setState(readStored(storageKey, defaultsRef.current));
  }

  const write = useCallback(
    (patch: Partial<PersistedTableState>) => {
      setState((prev) => {
        const next = { ...prev, ...patch };
        try {
          setItem(storageKey, JSON.stringify(next));
        } catch {
          // Quota errors, malformed storage — persistence is best-effort.
        }
        return next;
      });
    },
    [storageKey]
  );

  const setGrouping = useCallback((next: GroupingState) => write({ grouping: next }), [write]);
  const setSorting = useCallback((next: SortingState) => write({ sorting: next }), [write]);

  return [state, { setGrouping, setSorting }];
}

const readStored = (
  storageKey: string,
  defaults?: Partial<PersistedTableState>
): PersistedTableState => {
  const fallback: PersistedTableState = { ...EMPTY, ...defaults };
  const raw = getItem(storageKey);
  if (!raw) return fallback;
  try {
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return fallback;
    const { grouping, sorting } = parsed as Partial<PersistedTableState>;
    return {
      // A missing half (a table that only ever writes one) keeps its default;
      // an explicitly empty one is a real answer and stays empty.
      grouping: Array.isArray(grouping)
        ? grouping.filter((id) => typeof id === "string")
        : fallback.grouping,
      sorting: Array.isArray(sorting)
        ? sorting.filter(
            (entry): entry is SortingState[number] =>
              entry !== null &&
              typeof entry === "object" &&
              typeof (entry as SortingState[number]).id === "string" &&
              typeof (entry as SortingState[number]).desc === "boolean"
          )
        : fallback.sorting,
    };
  } catch {
    return fallback;
  }
};
