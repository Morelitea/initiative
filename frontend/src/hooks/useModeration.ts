/**
 * A community's moderation reports, and settling them.
 *
 * Who may read any of this is decided by the database — the tables admit the
 * people who already see everything in the initiative, plus guild admins — so
 * these hooks carry no gate of their own. The initiative's `can.moderate` is
 * the same question, asked of the same function, for whether the surface is
 * offered.
 */

import { useQuery } from "@tanstack/react-query";

import type {
  InitiativeSharingRead,
  ModerationReportList,
  ModerationReportRead,
  ReportSettle,
} from "@/api/generated/initiativeAPI.schemas";
import {
  getListReportsApiV1CGuildIdInitiativesInitiativeIdReportsGetQueryKey,
  getReadInitiativeSharingApiV1CGuildIdInitiativesInitiativeIdSharingGetQueryKey,
  listReportsApiV1CGuildIdInitiativesInitiativeIdReportsGet,
  readInitiativeSharingApiV1CGuildIdInitiativesInitiativeIdSharingGet,
  settleReportApiV1CGuildIdReportsReportIdSettlePost,
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
    queryKey: getListReportsApiV1CGuildIdInitiativesInitiativeIdReportsGetQueryKey(
      guildId,
      initiativeId,
      { settled, limit: REPORTS_PAGE_SIZE, offset }
    ),
    queryFn: () =>
      listReportsApiV1CGuildIdInitiativesInitiativeIdReportsGet(guildId, initiativeId, {
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
        settleReportApiV1CGuildIdReportsReportIdSettlePost(guildId, reportId, body),
      // Both lists move: the report leaves the open one and joins the settled.
      invalidate: () => invalidate(q.moderationReports(initiativeId)),
    },
    options
  );

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
    queryKey: getReadInitiativeSharingApiV1CGuildIdInitiativesInitiativeIdSharingGetQueryKey(
      guildId,
      initiativeId
    ),
    queryFn: () =>
      readInitiativeSharingApiV1CGuildIdInitiativesInitiativeIdSharingGet(guildId, initiativeId),
    ...options,
  });
