import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { createContext, useContext } from "react";

import {
  getReadBadgesApiV1GGuildIdDocumentBadgesGetQueryKey,
  readBadgesApiV1GGuildIdDocumentBadgesGet,
} from "@/api/generated/document-badges/document-badges";
import type { BadgeState } from "@/api/generated/initiativeAPI.schemas";
import { useActiveGuildId } from "@/hooks/useActiveGuildId";

/** How long a chip may be behind the thing it is about. */
const STALE_MS = 30_000;
/** How often an open document asks again while its tab is in front. */
const POLL_MS = 60_000;

/**
 * Every chip on one page, in one request.
 *
 * A document with thirty badges makes one call, not thirty: the plugin collects
 * the references out of the editor and asks for them together. Refs are sorted
 * so that the same page produces the same cache key however the nodes are
 * ordered.
 */
export const useDocumentBadges = (refs: string[], enabled = true) => {
  const guildId = useActiveGuildId();
  const ref = [...new Set(refs)].sort();
  const params = { ref };
  return useQuery({
    queryKey: getReadBadgesApiV1GGuildIdDocumentBadgesGetQueryKey(guildId, params),
    queryFn: () => readBadgesApiV1GGuildIdDocumentBadgesGet(guildId, params),
    enabled: enabled && guildId != null && ref.length > 0,
    staleTime: STALE_MS,
    // A badge goes stale because someone else moved something, so it is asked
    // again on a timer rather than waiting for this reader to do anything.
    // React Query pauses this while the tab is in the background.
    refetchInterval: POLL_MS,
    placeholderData: keepPreviousData,
  });
};

/** What the chips on this page currently say, by reference. */
export const BadgeStatesContext = createContext<Map<string, BadgeState>>(new Map());

export const useBadgeState = (ref: string): BadgeState | undefined =>
  useContext(BadgeStatesContext).get(ref);
