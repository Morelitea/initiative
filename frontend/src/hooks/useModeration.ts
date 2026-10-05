/**
 * A community's moderation reports, and settling them.
 *
 * Who may read any of this is decided by the database — the tables admit the
 * people who already see everything in the initiative, plus community admins — so
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
  getListReportsQueryKey,
  getReadInitiativeSharingQueryKey,
  listReports,
  readInitiativeSharing,
  settleReport,
} from "@/api/generated/moderation/moderation";
import { invalidate, q } from "@/api/query-keys";
import { useApiMutation } from "@/hooks/useApiMutation";
import type { MutationOpts } from "@/types/mutation";
import type { QueryOpts } from "@/types/query";

/** How many reports one page holds. */
export const REPORTS_PAGE_SIZE = 50;

interface ReportsParams {
  communityId: number;
  initiativeId: number;
  settled?: boolean;
  page?: number;
}

export const useModerationReports = (
  { communityId, initiativeId, settled = false, page = 1 }: ReportsParams,
  options?: QueryOpts<ModerationReportList>
) =>
  useQuery<ModerationReportList>({
    queryKey: getListReportsQueryKey(communityId, initiativeId, {
      settled,
      page,
      page_size: REPORTS_PAGE_SIZE,
    }),
    queryFn: () =>
      listReports(communityId, initiativeId, {
        settled,
        page,
        page_size: REPORTS_PAGE_SIZE,
      }),
    ...options,
  });

export const useSettleReport = (
  communityId: number,
  initiativeId: number,
  options?: MutationOpts<ModerationReportRead, { reportId: number; body: ReportSettle }>
) =>
  useApiMutation<ModerationReportRead, { reportId: number; body: ReportSettle }>(
    {
      mutationFn: ({ reportId, body }) => settleReport(communityId, reportId, body),
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
  communityId: number,
  initiativeId: number,
  options?: QueryOpts<InitiativeSharingRead>
) =>
  useQuery<InitiativeSharingRead>({
    queryKey: getReadInitiativeSharingQueryKey(communityId, initiativeId),
    queryFn: () => readInitiativeSharing(communityId, initiativeId),
    ...options,
  });
