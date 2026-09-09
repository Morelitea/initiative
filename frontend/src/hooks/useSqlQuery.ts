import { keepPreviousData, useQuery } from "@tanstack/react-query";

import { runWidgetQueryApiV1GGuildIdDashboardsDashboardIdWidgetsWidgetIdQueryGet } from "@/api/generated/dashboards/dashboards";
import type { QueryResponse } from "@/api/generated/initiativeAPI.schemas";
import { runQueryApiV1GGuildIdQueryPost } from "@/api/generated/query/query";
import { useActiveGuildId } from "@/hooks/useActiveGuildId";
import type { QueryOpts } from "@/types/query";

/**
 * Run one statement and cache what it returned.
 *
 * A read that happens to be spelled as a POST — a statement is too long for a
 * query string and would be logged everywhere one goes. So the caching this
 * needs is stated here rather than taken from the generated mutation hook,
 * which has none: two tiles running the same statement share one request, and a
 * canvas of them re-runs on the same terms as every other list on the page.
 *
 * The key carries the statement itself, because the statement *is* the request
 * — and the initiative beside it, because the same statement asked about two
 * initiatives is two different answers.
 */
export const sqlQueryKey = (guildId: number, sql: string, initiativeId?: number) =>
  ["query", guildId, sql, initiativeId ?? null] as const;

/** A placed widget's own read. Keyed by where it sits rather than by what it
 *  asks, because the statement is the server's to look up — the whole point of
 *  the endpoint behind it. */
export const widgetQueryKey = (guildId: number, dashboardId: number, widgetId: string) =>
  ["query", "widget", guildId, dashboardId, widgetId] as const;

/**
 * `initiativeId` narrows the answer to one initiative.
 *
 * A statement names datasets, not a scope, so a surface that belongs to an
 * initiative has to say which one or it gets every initiative its reader is in.
 * The narrowing is applied by the policies on the tables the statement reads,
 * so it removes rows and never adds any.
 */
export const useSqlQuery = (
  sql: string | null,
  initiativeId: number | undefined,
  options?: QueryOpts<QueryResponse>
) => {
  const guildId = useActiveGuildId();
  return useQuery<QueryResponse>({
    queryKey: sqlQueryKey(guildId, sql ?? "", initiativeId),
    queryFn: () =>
      runQueryApiV1GGuildIdQueryPost(guildId, { sql: sql ?? "", initiative_id: initiativeId }),
    // Not retried: a statement either resolves against the registry or it does
    // not, and a refused one is refused the same way every time.
    retry: false,
    ...options,
    enabled: Boolean(sql) && (options?.enabled ?? true),
  });
};

/**
 * The statement stored on one widget of one dashboard.
 *
 * The request names the widget and nothing else: what runs is the statement on
 * it, looked up server-side. That is what lets a dashboard show rows a reader
 * could not otherwise reach — the question is the one somebody published, and
 * a reader has no way to ask a different one of the same grants.
 */
export const useWidgetQuery = (
  dashboardId: number | null,
  widgetId: string | null,
  options?: QueryOpts<QueryResponse>
) => {
  const guildId = useActiveGuildId();
  const addressed = Boolean(dashboardId && widgetId);
  return useQuery<QueryResponse>({
    queryKey: widgetQueryKey(guildId, dashboardId ?? 0, widgetId ?? ""),
    queryFn: () =>
      runWidgetQueryApiV1GGuildIdDashboardsDashboardIdWidgetsWidgetIdQueryGet(
        guildId,
        dashboardId as number,
        widgetId as string
      ),
    // Not retried, for the same reason: a statement either resolves against the
    // registry or it does not.
    retry: false,
    // Keyed by where the widget sits, and a canvas re-renders with its
    // dashboard momentarily unknown — while its own read is in flight, or on
    // the way back from one. Without this the key changes under the tile and
    // it blanks to a fresh entry with nothing in it, so a dashboard that was
    // showing figures shows none for a beat and then shows them again. The
    // last answer stays on screen until the next one is ready.
    placeholderData: keepPreviousData,
    ...options,
    enabled: addressed && (options?.enabled ?? true),
  });
};
