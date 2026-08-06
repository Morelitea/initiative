import { useSearch } from "@tanstack/react-router";
import { type Dispatch, type SetStateAction, useEffect, useRef, useState } from "react";

import { useGuilds } from "@/hooks/useGuilds";

/** Sentinel filter value meaning "no initiative filter — show every initiative". */
export const INITIATIVE_FILTER_ALL = "all";

interface UseInitiativeFilterOptions {
  /**
   * When a view is pinned to one initiative (e.g. an initiative detail page),
   * pass its id. The filter is held at that initiative and the URL /
   * guild-change effects are skipped. Pass `null` for the standalone tool-list
   * pages that let the user pick an initiative.
   */
  lockedInitiativeId: number | null;
  /**
   * When true, clearing the `?initiativeId` search param resets the filter back
   * to ALL — this matches the Documents page's "All documents" navigation,
   * where arriving from an initiative-scoped view and then clearing the param
   * must drop the pin. When false (the default) an empty param is a no-op and
   * the current selection is kept.
   */
  resetOnParamCleared?: boolean;
}

interface UseInitiativeFilterResult {
  /** The dropdown value: an initiative id as a string, or {@link INITIATIVE_FILTER_ALL}. */
  initiativeFilter: string;
  setInitiativeFilter: Dispatch<SetStateAction<string>>;
  /** The active initiative id parsed for query/permission checks, or `null` for ALL. */
  filteredInitiativeId: number | null;
}

/**
 * The initiative-filter cluster shared by the tool-list pages (projects,
 * documents, queues, counters). Owns the filter value plus the three effects
 * that keep it coherent: consuming `?initiativeId` from the URL once, pinning to
 * a locked initiative, and resetting when the active guild changes (initiative
 * ids are guild-specific).
 */
export function useInitiativeFilter({
  lockedInitiativeId,
  resetOnParamCleared = false,
}: UseInitiativeFilterOptions): UseInitiativeFilterResult {
  const { activeGuildId } = useGuilds();
  const searchParams = useSearch({ strict: false }) as { initiativeId?: string };

  const [initiativeFilter, setInitiativeFilter] = useState<string>(
    lockedInitiativeId ? String(lockedInitiativeId) : INITIATIVE_FILTER_ALL
  );

  const filteredInitiativeId =
    initiativeFilter !== INITIATIVE_FILTER_ALL ? Number(initiativeFilter) : null;

  const lastConsumedParams = useRef<string>("");
  const prevGuildIdRef = useRef<number | null>(activeGuildId);

  // Consume ?initiativeId from the URL once. A locked view ignores the URL, and
  // an already-consumed value doesn't re-pin the filter (so the dropdown can
  // override the URL selection). Whether a cleared param resets to ALL is
  // controlled by resetOnParamCleared.
  useEffect(() => {
    if (lockedInitiativeId) return;
    const urlInitiativeId = searchParams.initiativeId;
    const paramKey = urlInitiativeId || "";
    if (paramKey === lastConsumedParams.current) return;
    if (!urlInitiativeId && !resetOnParamCleared) return;
    lastConsumedParams.current = paramKey;
    setInitiativeFilter(urlInitiativeId || INITIATIVE_FILTER_ALL);
  }, [searchParams, lockedInitiativeId, resetOnParamCleared]);

  // Keep the filter pinned to the locked initiative.
  useEffect(() => {
    if (lockedInitiativeId) {
      const lockedValue = String(lockedInitiativeId);
      setInitiativeFilter((prev) => (prev === lockedValue ? prev : lockedValue));
    }
  }, [lockedInitiativeId]);

  // Reset the initiative filter when the active guild changes (initiative IDs
  // are guild-specific), but not on initial mount.
  useEffect(() => {
    const prevGuildId = prevGuildIdRef.current;
    prevGuildIdRef.current = activeGuildId;
    if (prevGuildId !== null && prevGuildId !== activeGuildId && !lockedInitiativeId) {
      setInitiativeFilter(INITIATIVE_FILTER_ALL);
      lastConsumedParams.current = "";
    }
  }, [activeGuildId, lockedInitiativeId]);

  return { initiativeFilter, setInitiativeFilter, filteredInitiativeId };
}
