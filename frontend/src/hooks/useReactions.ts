/**
 * Reactions are read as part of whatever carries them — a comment arrives with
 * its `reactions` already filled — so there is no list query here, only the
 * toggle and the suggested set.
 */

import { useQuery } from "@tanstack/react-query";

import type { ReactionSummary, ReactionTarget } from "@/api/generated/initiativeAPI.schemas";
import {
  getSuggestedReactionsApiV1GGuildIdReactionsSuggestedGetQueryKey,
  suggestedReactionsApiV1GGuildIdReactionsSuggestedGet,
  toggleReactionApiV1GGuildIdReactionsTargetTypeTargetIdPut,
} from "@/api/generated/reactions/reactions";
import { invalidateAllComments } from "@/api/query-keys";
import { useActiveGuildId } from "@/hooks/useActiveGuildId";
import { useGuildMutation } from "@/hooks/useApiMutation";
import type { MutationOpts } from "@/types/mutation";
import type { QueryOpts } from "@/types/query";

/** What each reaction target invalidates once its reactions move. */
const INVALIDATE_BY_TARGET: Record<ReactionTarget, () => void> = {
  comment: () => void invalidateAllComments(),
};

/**
 * The emoji every picker offers first. Served by the backend so the row is one
 * product-wide decision — the same suggestions for everyone, rather than
 * whatever each browser happened to pick last.
 */
export const useSuggestedReactions = (options?: QueryOpts<string[]>) => {
  const guildId = useActiveGuildId();
  return useQuery<string[]>({
    queryKey: getSuggestedReactionsApiV1GGuildIdReactionsSuggestedGetQueryKey(guildId),
    queryFn: () => suggestedReactionsApiV1GGuildIdReactionsSuggestedGet(guildId),
    // A fixed list; there is no reason to ask again this session.
    staleTime: Number.POSITIVE_INFINITY,
    ...options,
  });
};

export interface ToggleReactionVars {
  targetType: ReactionTarget;
  targetId: number;
  emoji: string;
}

/**
 * Add this emoji, or take it back if it is already yours. The reply is the
 * target's whole reaction state, so the caller can render from it directly
 * while the invalidated queries refetch.
 */
export const useToggleReaction = (options?: MutationOpts<ReactionSummary, ToggleReactionVars>) =>
  useGuildMutation<ReactionSummary, ToggleReactionVars>(
    {
      mutationFn: (guildId, { targetType, targetId, emoji }) =>
        toggleReactionApiV1GGuildIdReactionsTargetTypeTargetIdPut(guildId, targetType, targetId, {
          emoji,
        }),
      invalidate: (_data, vars) => INVALIDATE_BY_TARGET[vars.targetType]?.(),
      errorKey: "common:reactions.error",
    },
    options
  );
