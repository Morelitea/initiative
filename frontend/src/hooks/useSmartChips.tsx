import { useQueries, useQuery } from "@tanstack/react-query";

import type {
  ReferenceEmbed,
  SearchEntityType,
  SmartChipState,
} from "@/api/generated/initiativeAPI.schemas";
import { readReferenceEmbeds, readSmartChips } from "@/api/generated/smart-chips/smart-chips";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { referenceRef, storedEntityType } from "@/lib/smartChips";

/** How long an answer is trusted when nothing has said it changed — what a
 *  remount or a tab brought forward asks again after. */
const STALE_MS = 30_000;
/**
 * How often a chip asks again with nothing having said it changed.
 *
 * The realtime bus is what keeps a chip current: a change to the thing it is
 * about marks it stale the moment it lands. This only covers what the bus
 * cannot deliver — something in an initiative this tab's socket did not join.
 */
const BACKSTOP_MS = 5 * 60_000;

/**
 * How many references one request may carry — the server's own ceilings
 * (`MAX_REFS`, `MAX_EMBEDS`), which it enforces by refusing the request rather
 * than answering part of it. A moment that asks for more sends several.
 */
export const REFS_PER_REQUEST = 500;
export const EMBEDS_PER_REQUEST = 25;

interface Waiter<T> {
  resolve: (value: T | null) => void;
  reject: (error: unknown) => void;
}

/**
 * One request for everything asked in the same moment.
 *
 * Every chip asks for itself, and a page of thirty still makes one call: the
 * asks made while a render commits are held for a tick, then sent together,
 * split at `limit`. Each ask is answered with its own item, or `null` where
 * the server left it out — gone, or not this reader's to see.
 */
export const batchedReader = <T extends { ref: string }>(
  read: (communityId: number, refs: string[]) => Promise<T[]>,
  limit: number
) => {
  const pending = new Map<number, Map<string, Waiter<T>[]>>();

  const send = (communityId: number, waiting: Map<string, Waiter<T>[]>) => {
    const refs = [...waiting.keys()];
    for (let index = 0; index < refs.length; index += limit) {
      const chunk = refs.slice(index, index + limit);
      const settle = (answer: (waiter: Waiter<T>, ref: string) => void) => {
        for (const ref of chunk) for (const waiter of waiting.get(ref) ?? []) answer(waiter, ref);
      };
      read(communityId, chunk).then(
        (items) => {
          const byRef = new Map(items.map((item) => [item.ref, item]));
          settle((waiter, ref) => waiter.resolve(byRef.get(ref) ?? null));
        },
        (error) => settle((waiter) => waiter.reject(error))
      );
    }
  };

  return (communityId: number, ref: string): Promise<T | null> =>
    new Promise((resolve, reject) => {
      let waiting = pending.get(communityId);
      if (!waiting) {
        const held = new Map<string, Waiter<T>[]>();
        waiting = held;
        pending.set(communityId, held);
        setTimeout(() => {
          pending.delete(communityId);
          send(communityId, held);
        }, 0);
      }
      waiting.set(ref, [...(waiting.get(ref) ?? []), { resolve, reject }]);
    });
};

const loadChip = batchedReader(
  (communityId, refs) => readSmartChips(communityId, { refs }).then((answer) => answer.items),
  REFS_PER_REQUEST
);

const loadEmbed = batchedReader(
  (communityId, refs) => readReferenceEmbeds(communityId, { refs }).then((answer) => answer.items),
  EMBEDS_PER_REQUEST
);

/** The thing a reference is about, as its cache address names it: a body
 *  saved under an earlier spelling of a kind is kept with today's. */
const subject = (ref: string) => {
  const [kind, id] = ref.split(":");
  return `${storedEntityType(kind) ?? kind}/${id}`;
};

/**
 * Where one chip's answer is kept: addressed like a read of its own, by the
 * thing it is about and then the fact, so a change to the thing names every
 * chip about it at once (`q.references(kind, id)`).
 */
export const chipKey = (communityId: number, ref: string) =>
  [`/api/v1/c/${communityId}/smart-chips/${subject(ref)}`, ref] as const;

const embedKey = (communityId: number, ref: string) =>
  [`/api/v1/c/${communityId}/smart-chips/embeds/${subject(ref)}`, ref] as const;

/** When a reading turns on its own — a due date passing, an event starting —
 *  the chip asks again at that moment, rather than on a timer. */
const nextAsk = (state: SmartChipState | null | undefined): number => {
  const until = state?.date ? Date.parse(state.date) - Date.now() : Number.NaN;
  return until > 0 && until < BACKSTOP_MS ? until + 1_000 : BACKSTOP_MS;
};

const chipQuery = (communityId: number, ref: string, enabled = true) => ({
  queryKey: chipKey(communityId, ref),
  queryFn: () => loadChip(communityId, ref),
  enabled: enabled && communityId > 0,
  staleTime: STALE_MS,
  refetchInterval: (query: { state: { data?: SmartChipState | null } }) =>
    nextAsk(query.state.data),
});

/**
 * What one reference says right now, or `undefined` while it loads and where
 * it cannot be read — deleted, or never shared with this reader.
 *
 * A chip asks `task:12:status`, a link asks `task:12`. Each asks for itself;
 * the reader gathers whatever a page asks in one moment into one request.
 * `communityId` reads it in a community other than the page's, for a surface
 * that spans communities.
 */
export const useChipState = (ref: string, communityId?: number): SmartChipState | undefined => {
  const active = useActiveCommunityId();
  return useQuery(chipQuery(communityId ?? active, ref)).data ?? undefined;
};

/** The answers a list of references has so far.
 *
 * Module scope so its identity is stable: `combine` runs on every render, and
 * a fresh function here would rebuild the result each time. */
const combineStates = (results: { data?: SmartChipState | null; isFetched: boolean }[]) => ({
  states: results.flatMap((result) => (result.data ? [result.data] : [])),
  isFetched: results.every((result) => result.isFetched),
});

/** What every reference in a list says right now — for a surface that holds
 *  its references as data rather than as nodes: a list of links, a thread. */
export const useChipStates = (refs: string[], enabled = true, communityId?: number) => {
  const active = useActiveCommunityId();
  return useQueries({
    queries: refs.map((ref) => chipQuery(communityId ?? active, ref, enabled)),
    combine: combineStates,
  });
};

/** What a referenced thing is called right now, or `undefined` where it cannot
 *  be read — deleted, or never shared with this reader. */
export const useReferenceTitle = (
  entityType: SearchEntityType,
  entityId: number
): string | undefined => useChipState(referenceRef(entityType, entityId))?.text || undefined;

/**
 * What an embedded reference shows — the thing's name and its description —
 * or `null` where it cannot be read. Kept current the way a chip is: a change
 * to the thing marks it stale.
 */
export const useReferenceEmbed = (entityType: SearchEntityType, entityId: number) => {
  const communityId = useActiveCommunityId();
  const ref = referenceRef(entityType, entityId);
  return useQuery<ReferenceEmbed | null>({
    queryKey: embedKey(communityId, ref),
    queryFn: () => loadEmbed(communityId, ref),
    enabled: communityId > 0,
    staleTime: STALE_MS,
  });
};
