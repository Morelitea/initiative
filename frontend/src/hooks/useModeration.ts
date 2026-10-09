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
  ModerationActCreate,
  ModerationActionRead,
  ModerationLogList,
  ModerationReportList,
  ModerationReportRead,
  ReportSettle,
} from "@/api/generated/initiativeAPI.schemas";
import {
  getListReportsQueryKey,
  getReadInitiativeSharingQueryKey,
  getReadModerationLogQueryKey,
  listReports,
  moderate,
  readInitiativeSharing,
  readModerationLog,
  restoreRemoval,
  settleReport,
} from "@/api/generated/moderation/moderation";
import { useApiMutation } from "@/hooks/useApiMutation";
import { refreshAfterHolding } from "@/hooks/useHolds";
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
  _initiativeId: number,
  options?: MutationOpts<ModerationReportRead, { reportId: number; body: ReportSettle }>
) =>
  useApiMutation<ModerationReportRead, { reportId: number; body: ReportSettle }>(
    {
      mutationFn: ({ reportId, body }) => settleReport(communityId, reportId, body),
      // Both lists move: the report leaves the open one and joins the settled.
      // Settling may also have taken the reported thing down, wherever it
      // was shown, and written the log.
      invalidate: refreshAfterHolding,
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

/**
 * A moderator acting on something directly: taking it down, locking its
 * thread, clearing its reactions, warning whoever wrote it.
 */
export const useModerate = (
  communityId: number,
  options?: MutationOpts<ModerationActionRead, ModerationActCreate>
) =>
  useApiMutation<ModerationActionRead, ModerationActCreate>(
    {
      mutationFn: (body) => moderate(communityId, body),
      // What was taken down, locked or cleared changes wherever it is shown.
      invalidate: refreshAfterHolding,
      errorKey: "moderation:act.error",
    },
    options
  );

/** Putting back what a removal took down. */
export const useRestoreRemoval = (
  communityId: number,
  options?: MutationOpts<ModerationActionRead, number>
) =>
  useApiMutation<ModerationActionRead, number>(
    {
      mutationFn: (actionId) => restoreRemoval(communityId, actionId, {}),
      invalidate: refreshAfterHolding,
      errorKey: "moderation:log.restoreError",
    },
    options
  );

/** How many log rows one page holds. */
export const LOG_PAGE_SIZE = 50;

/** What an initiative's moderators have done, newest first. */
export const useModerationLog = (
  {
    communityId,
    initiativeId,
    page = 1,
  }: { communityId: number; initiativeId: number; page?: number },
  options?: QueryOpts<ModerationLogList>
) =>
  useQuery<ModerationLogList>({
    queryKey: getReadModerationLogQueryKey(communityId, initiativeId, {
      page,
      page_size: LOG_PAGE_SIZE,
    }),
    queryFn: () => readModerationLog(communityId, initiativeId, { page, page_size: LOG_PAGE_SIZE }),
    ...options,
  });
