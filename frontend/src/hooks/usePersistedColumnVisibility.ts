import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { VisibilityState } from "@tanstack/react-table";

import { getItem, setItem } from "@/lib/storage";

type Updater = VisibilityState | ((prev: VisibilityState) => VisibilityState);

/**
 * TanStack ``columnVisibility`` state persisted to our @/lib/storage wrapper
 * (localStorage on web, Capacitor Preferences on native, always synchronous).
 *
 * - ``defaultHiddenIds`` seeds the initial state: any id in this list that
 *   has no explicit persisted value is rendered as ``false`` (hidden) so
 *   newly-added property columns default to hidden without any caller
 *   ceremony.
 * - Any previously-persisted ids that no longer appear in ``defaultHiddenIds``
 *   are kept untouched (TanStack ignores unknown ids). We don't auto-prune
 *   the stored map so that toggles persist across transient empty states
 *   (e.g. a React Query refetch returning an empty list for a tick).
 */
export function usePersistedColumnVisibility(
  storageKey: string,
  defaultHiddenIds: string[]
): [VisibilityState, (updater: Updater) => void] {
  const defaultsRef = useRef<string[]>(defaultHiddenIds);
  defaultsRef.current = defaultHiddenIds;

  const [state, setState] = useState<VisibilityState>(() => {
    const stored = readStored(storageKey);
    return mergeDefaults(stored, defaultHiddenIds);
  });

  // Merge in new default-hidden ids on subsequent renders (e.g. property
  // definitions loaded asynchronously) without clobbering explicit toggles.
  const defaultsKey = useMemo(() => defaultHiddenIds.join(","), [defaultHiddenIds]);
  useEffect(() => {
    setState((prev) => mergeDefaults(prev, defaultsRef.current));
    // Intentionally only re-run when the set of defaults changes.
  }, [defaultsKey]);

  const write = useCallback(
    (updater: Updater) => {
      setState((prev) => {
        const next = typeof updater === "function" ? updater(prev) : updater;
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

  return [state, write];
}

const readStored = (storageKey: string): VisibilityState => {
  const raw = getItem(storageKey);
  if (!raw) return {};
  try {
    const parsed = JSON.parse(raw);
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
      const out: VisibilityState = {};
      for (const [key, value] of Object.entries(parsed)) {
        if (typeof value === "boolean") out[key] = value;
      }
      return out;
    }
    return {};
  } catch {
    return {};
  }
};

const mergeDefaults = (state: VisibilityState, defaultHiddenIds: string[]): VisibilityState => {
  let changed = false;
  const next: VisibilityState = { ...state };
  for (const id of defaultHiddenIds) {
    if (!(id in next)) {
      next[id] = false;
      changed = true;
    }
  }
  return changed ? next : state;
};
