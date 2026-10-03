/**
 * The My Tools page's data: one tool at a time, across every community the
 * reader belongs to.
 *
 * One `/me/*` list per tool, and one counts call. The lists are the community-wide
 * ones with the community boundary taken off — same rows, same filters, merged
 * server-side — so the rows they produce go through the same `lib/toolRows`
 * builder the community front page uses, and the query that lists each tool
 * comes from the same `TOOL_HOOKS` table its community-wide twin reads.
 */

import { keepPreviousData, useQueries, useQuery } from "@tanstack/react-query";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";

import type { MyToolCountsResponse, Tool } from "@/api/generated/initiativeAPI.schemas";
import { getGetMyToolCountsQueryKey, getMyToolCounts } from "@/api/generated/my-tools/my-tools";
import type { ToolMyListParams } from "@/hooks/toolHooks";
import { TOOL_HOOKS } from "@/hooks/toolHooks";
import type { ToolRow } from "@/lib/toolRows";
import { buildToolRows, oneToolResponse } from "@/lib/toolRows";
import { TOOLS } from "@/lib/tools";
import type { QueryOpts } from "@/types/query";

/**
 * What every `/me/{tool}` list takes. The nine endpoints accept the same set —
 * that is what lets one table drive all of them — so the page builds one
 * params object rather than nine.
 */
export type MyToolListParams = ToolMyListParams;

/** How much of each tool reaches the reader — which tabs the page draws. */
export const useMyToolCounts = (
  params?: { community_ids?: number[]; created_by_me?: boolean },
  options?: QueryOpts<MyToolCountsResponse>
) =>
  useQuery<MyToolCountsResponse>({
    queryKey: getGetMyToolCountsQueryKey(params),
    queryFn: () => getMyToolCounts(params),
    staleTime: 30_000,
    ...options,
  });

/** How the My Tools table is narrowed and ordered. */
export interface MyToolQuery {
  /** Communities to keep, or none for all of them. */
  communityIds?: number[];
  /** Case-insensitive match on the name, searched across the whole set. */
  search?: string;
  /** The page's other view: only what the reader wrote. */
  createdByMe?: boolean;
  /** One of `name`, `updated_at` — there is no cross-community initiative order. */
  sortBy?: string;
  sortDir?: "asc" | "desc";
}

/**
 * One cross-community page of whatever tool My Tools is showing.
 *
 * Twin of `useCommunityToolRows`: all nine lists are asked so the fan-out never
 * changes shape, and every one but the selected tool is gated off.
 */
export function useMyToolRows(tool: Tool, page: number, pageSize: number, view: MyToolQuery = {}) {
  const { t } = useTranslation("communityHome");

  const params: MyToolListParams = {
    page,
    page_size: pageSize,
    ...(view.communityIds && view.communityIds.length > 0
      ? { community_ids: view.communityIds }
      : {}),
    ...(view.search ? { search: view.search } : {}),
    ...(view.createdByMe ? { created_by_me: true } : {}),
    ...(view.sortBy ? { sort_by: view.sortBy, sort_dir: view.sortDir ?? "asc" } : {}),
  };

  const results = useQueries({
    queries: TOOLS.map((candidate) => ({
      ...TOOL_HOOKS[candidate].myListQuery(params),
      enabled: candidate === tool,
      placeholderData: keepPreviousData,
    })),
  });
  const query = results[TOOLS.indexOf(tool)];

  const rows = useMemo<ToolRow[]>(
    // Every row across communities carries its own community id, so there is no
    // community for a fallback to stand in for.
    () => buildToolRows(tool, oneToolResponse(tool, query.data), t, 0),
    [tool, query.data, t]
  );

  return {
    rows,
    totalCount: query.data?.total_count ?? 0,
    isLoading: query.isLoading,
    isError: query.isError,
  };
}

/**
 * The tools with something behind them, in registry order.
 *
 * A reader who is in no queue anywhere is not offered a queue tab — an empty
 * table of a tool they have never used says nothing. Before the counts land,
 * no tab is drawn rather than six that might vanish.
 */
export const toolsWithContent = (counts: MyToolCountsResponse | undefined): Tool[] =>
  counts ? TOOLS.filter((tool) => (counts.counts[tool] ?? 0) > 0) : [];
