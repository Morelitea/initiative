import { keepPreviousData, useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { createContext, useCallback, useContext, useMemo, useState } from "react";

import type { SearchEntityType, SmartChipState } from "@/api/generated/initiativeAPI.schemas";
import {
  getReadSmartChipsApiV1GGuildIdSmartChipsGetQueryKey,
  readSmartChipsApiV1GGuildIdSmartChipsGet,
} from "@/api/generated/smart-chips/smart-chips";
import { useActiveGuildId } from "@/hooks/useActiveGuildId";
import { referenceRef } from "@/lib/smartChips";

/** How long a chip may be behind the thing it is about. */
const STALE_MS = 30_000;
/** How often an open document asks again while its tab is in front. */
const POLL_MS = 60_000;

/**
 * Every chip on one page, in one request.
 *
 * A document with thirty chips makes one call, not thirty: the scope collects
 * the references out of the editor and asks for them together. Refs are sorted
 * so that the same page produces the same cache key however the nodes are
 * ordered.
 */
export const useSmartChipStates = (refs: string[], enabled = true) => {
  const guildId = useActiveGuildId();
  const ref = [...new Set(refs)].sort();
  const params = { ref };
  return useQuery({
    queryKey: getReadSmartChipsApiV1GGuildIdSmartChipsGetQueryKey(guildId, params),
    queryFn: () => readSmartChipsApiV1GGuildIdSmartChipsGet(guildId, params),
    enabled: enabled && guildId != null && ref.length > 0,
    staleTime: STALE_MS,
    // A chip goes stale because someone else moved something, so it is asked
    // again on a timer rather than waiting for this reader to do anything.
    // React Query pauses this while the tab is in the background.
    refetchInterval: POLL_MS,
    placeholderData: keepPreviousData,
  });
};

interface SmartChipScopeValue {
  /** What everything on this page currently says, by reference. */
  states: Map<string, SmartChipState>;
  /** What the page refers to, handed up by whatever can see the content. */
  report: (refs: string[]) => void;
}

const SmartChipScopeContext = createContext<SmartChipScopeValue>({
  states: new Map(),
  report: () => {},
});

/**
 * The page's live answers, above the thing that renders the chips.
 *
 * This sits **outside** the editor rather than being one of its plugins, and
 * that placement is the whole point. Chips are Lexical decorators, which the
 * composer renders as portals of its own — a provider mounted among the plugins
 * is not an ancestor of any of them, so every chip would read an empty map and
 * show the words stored beside it instead of the live reading.
 *
 * Content is reported up (`report`) rather than walked here, because only
 * something inside the editor can see the document.
 */
export function SmartChipScope({ children }: { children: ReactNode }) {
  const [refs, setRefs] = useState<string[]>([]);

  const report = useCallback((next: string[]) => {
    // Compared as a string so an edit that moves a reference without changing
    // the set does not start a new request.
    setRefs((current) => (current.join() === next.join() ? current : next));
  }, []);

  const { data } = useSmartChipStates(refs);

  const value = useMemo(() => {
    const states = new Map<string, SmartChipState>();
    for (const state of data?.items ?? []) states.set(state.ref, state);
    return { states, report };
  }, [data, report]);

  return <SmartChipScopeContext.Provider value={value}>{children}</SmartChipScopeContext.Provider>;
}

/** How a page tells its scope what it refers to. */
export const useReportReferences = () => useContext(SmartChipScopeContext).report;

/** What everything this page refers to currently says, by reference.
 *
 * Chips and links read from the same map: a chip asks `task:12:status`, a link
 * asks `task:12`, and both came back in one request. */
export const useChipState = (ref: string): SmartChipState | undefined =>
  useContext(SmartChipScopeContext).states.get(ref);

/** What a referenced thing is called right now, or `undefined` where it cannot
 *  be read — deleted, or never shared with this reader. */
export const useReferenceTitle = (
  entityType: SearchEntityType,
  entityId: number
): string | undefined => useChipState(referenceRef(entityType, entityId))?.text || undefined;
