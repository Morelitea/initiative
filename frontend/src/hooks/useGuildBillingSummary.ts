import { useQuery } from "@tanstack/react-query";

import {
  getReadCommunityBillingSummaryQueryKey,
  readCommunityBillingSummary,
} from "@/api/generated/communities/communities";
import type { CommunityBillingSummaryRead } from "@/api/generated/initiativeAPI.schemas";
import { useAppConfig } from "@/hooks/useAppConfig";
import type { GuildEntry } from "@/hooks/useGuilds";
import { holdsBillingSeat } from "@/lib/billingSummary";

/**
 * The community's plan as the billing service tells it, for its seat.
 *
 * Asked only where there is a portal and only by the seat's own holder — the
 * route is the handoff mint's, and a grantee lent the seat is never shown a
 * plan (`holdsBillingSeat`). The settings tab's badge and the panel on the tab read the
 * same query, so opening the tab is one request. The route answers
 * `available: false` when billing does not; an error is a refusal, which
 * asking again does not change.
 */
export const useGuildBillingSummary = (guild: GuildEntry | null | undefined) => {
  const { billing } = useAppConfig();
  const guildId = guild?.id ?? 0;
  return useQuery<CommunityBillingSummaryRead>({
    queryKey: getReadCommunityBillingSummaryQueryKey(guildId),
    queryFn: () => readCommunityBillingSummary(guildId),
    enabled: Boolean(billing) && holdsBillingSeat(guild),
    retry: false,
    staleTime: 60_000,
  });
};
