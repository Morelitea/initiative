import { keepPreviousData, useQueries } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { createContext, useCallback, useContext, useMemo, useState } from "react";

import type {
  SearchEntityType,
  SmartChipState,
  SmartChipStateList,
} from "@/api/generated/initiativeAPI.schemas";
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
 * How many references one request may carry — the server's own ceiling, which
 * it enforces by refusing the request rather than answering part of it.
 *
 * A page longer than this asks in several requests instead of one, so what a
 * page costs follows what is actually written in it. Every real document fits
 * in the first.
 */
export const REFS_PER_REQUEST = 100;

/** One page's references, split into what a request will carry. */
export const referenceBatches = (refs: string[]): string[][] => {
  // Sorted first, so the same page splits the same way however its nodes are
  // ordered and each batch keeps a stable cache key.
  const sorted = [...new Set(refs)].sort();
  const batches: string[][] = [];
  for (let index = 0; index < sorted.length; index += REFS_PER_REQUEST) {
    batches.push(sorted.slice(index, index + REFS_PER_REQUEST));
  }
  return batches;
};

/** The batches read back as one answer.
 *
 * Module scope so its identity is stable: `combine` runs on every render, and
 * a fresh function here would rebuild the result — and every chip below it —
 * each time the document is touched. */
const combineBatches = (results: { data?: SmartChipStateList; isFetched: boolean }[]) => ({
  data: { items: results.flatMap((result) => result.data?.items ?? []) },
  isFetched: results.every((result) => result.isFetched),
});

/**
 * Everything one page refers to, in as few requests as it takes.
 *
 * A document with thirty chips makes one call, not thirty: the scope collects
 * the references out of the editor and asks for them together.
 */
export const useSmartChipStates = (refs: string[], enabled = true) => {
  const guildId = useActiveGuildId();
  const batches = referenceBatches(refs);
  return useQueries({
    queries: batches.map((ref) => ({
      queryKey: getReadSmartChipsApiV1GGuildIdSmartChipsGetQueryKey(guildId, { ref }),
      queryFn: () => readSmartChipsApiV1GGuildIdSmartChipsGet(guildId, { ref }),
      enabled: enabled && guildId != null,
      staleTime: STALE_MS,
      // A chip goes stale because someone else moved something, so it is asked
      // again on a timer rather than waiting for this reader to do anything.
      // React Query pauses this while the tab is in the background.
      refetchInterval: POLL_MS,
      placeholderData: keepPreviousData,
    })),
    combine: combineBatches,
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
 * asks `task:12`, and the page asked for both together. */
export const useChipState = (ref: string): SmartChipState | undefined =>
  useContext(SmartChipScopeContext).states.get(ref);

/** What a referenced thing is called right now, or `undefined` where it cannot
 *  be read — deleted, or never shared with this reader. */
export const useReferenceTitle = (
  entityType: SearchEntityType,
  entityId: number
): string | undefined => useChipState(referenceRef(entityType, entityId))?.text || undefined;
