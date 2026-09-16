/**
 * A community's moderation reports, and settling them.
 *
 * Who may read any of this is decided by the database — the tables admit the
 * people who already see everything in the initiative, plus guild admins — so
 * these hooks carry no gate of their own. `canModerate` below is what decides
 * whether the surface is *offered*, not whether it is allowed.
 */

import { useQuery } from "@tanstack/react-query";

import type {
  InitiativeRead,
  InitiativeSharingRead,
  ModerationReportList,
  ModerationReportRead,
  ReportSettle,
} from "@/api/generated/initiativeAPI.schemas";
import {
  getListReportsApiV1GGuildIdInitiativesInitiativeIdReportsGetQueryKey,
  getReadInitiativeSharingApiV1GGuildIdInitiativesInitiativeIdSharingGetQueryKey,
  listReportsApiV1GGuildIdInitiativesInitiativeIdReportsGet,
  readInitiativeSharingApiV1GGuildIdInitiativesInitiativeIdSharingGet,
  settleReportApiV1GGuildIdReportsReportIdSettlePost,
} from "@/api/generated/moderation/moderation";
import { invalidate, q } from "@/api/query-keys";
import { useApiMutation } from "@/hooks/useApiMutation";
import type { MutationOpts } from "@/types/mutation";
import type { QueryOpts } from "@/types/query";

/** How many reports one page holds. */
export const REPORTS_PAGE_SIZE = 50;

interface ReportsParams {
  guildId: number;
  initiativeId: number;
  settled?: boolean;
  offset?: number;
}

export const useModerationReports = (
  { guildId, initiativeId, settled = false, offset = 0 }: ReportsParams,
  options?: QueryOpts<ModerationReportList>
) =>
  useQuery<ModerationReportList>({
    queryKey: getListReportsApiV1GGuildIdInitiativesInitiativeIdReportsGetQueryKey(
      guildId,
      initiativeId,
      { settled, limit: REPORTS_PAGE_SIZE, offset }
    ),
    queryFn: () =>
      listReportsApiV1GGuildIdInitiativesInitiativeIdReportsGet(guildId, initiativeId, {
        settled,
        limit: REPORTS_PAGE_SIZE,
        offset,
      }),
    ...options,
  });

export const useSettleReport = (
  guildId: number,
  initiativeId: number,
  options?: MutationOpts<ModerationReportRead, { reportId: number; body: ReportSettle }>
) =>
  useApiMutation<ModerationReportRead, { reportId: number; body: ReportSettle }>(
    {
      mutationFn: ({ reportId, body }) =>
        settleReportApiV1GGuildIdReportsReportIdSettlePost(guildId, reportId, body),
      // Both lists move: the report leaves the open one and joins the settled.
      invalidate: () => invalidate(q.moderationReports(initiativeId)),
    },
    options
  );

/**
 * Whether to offer this initiative's moderation surface to the reader.
 *
 * The standing is "Full access" — the flag a role carries, not the name of the
 * built-in role, since roles are renameable and a community may define its own.
 * A guild admin clears every initiative gate and so is included here, matching
 * what the tables themselves admit.
 */
export const canModerate = (
  initiative: InitiativeRead,
  userId: number | undefined,
  isGuildAdmin: boolean
): boolean => {
  if (isGuildAdmin) return true;
  if (!userId) return false;
  return initiative.members.some((m) => m.user.id === userId && m.override_share_restrictions);
};

/**
 * Who can reach what, across the initiative.
 *
 * Refused to anybody without the standing the reports take, so it is only
 * asked for from the console.
 */
export const useInitiativeSharing = (
  guildId: number,
  initiativeId: number,
  options?: QueryOpts<InitiativeSharingRead>
) =>
  useQuery<InitiativeSharingRead>({
    queryKey: getReadInitiativeSharingApiV1GGuildIdInitiativesInitiativeIdSharingGetQueryKey(
      guildId,
      initiativeId
    ),
    queryFn: () =>
      readInitiativeSharingApiV1GGuildIdInitiativesInitiativeIdSharingGet(guildId, initiativeId),
    ...options,
  });
