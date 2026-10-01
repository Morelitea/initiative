/**
 * How much of each tool there is. Every figure is a count of the tool's own
 * list, so a badge always agrees with the list it sits on.
 *
 * - `useToolCountsByInitiative` answers every tool at once (tool → initiative
 *   id → count), spread over the registry's `TOOLS` so callers render
 *   whatever the registry declares rather than naming tools by hand.
 * - `useToolCounts` answers one tool's page: each of its views, and the tag
 *   tree beside the view being shown.
 */

import { keepPreviousData, useQuery } from "@tanstack/react-query";

import type {
  GetToolCountsApiV1CGuildIdToolsToolCountsGetParams,
  Tool,
  ToolCountsResponse,
} from "@/api/generated/initiativeAPI.schemas";
import {
  getGetToolCountsApiV1CGuildIdToolsToolCountsGetQueryKey,
  getGetToolCountsByInitiativeApiV1CGuildIdToolsCountsByInitiativeGetQueryKey,
  getToolCountsApiV1CGuildIdToolsToolCountsGet,
  getToolCountsByInitiativeApiV1CGuildIdToolsCountsByInitiativeGet,
} from "@/api/generated/tools/tools";
import { useActiveGuildId } from "@/hooks/useActiveGuildId";
import { TOOLS } from "@/lib/tools";

/** One tool's counts, by initiative id. */
export interface ToolCounts {
  counts: Map<number, number>;
  isLoading: boolean;
}

export type ToolCountsByInitiative = Record<Tool, ToolCounts>;

export interface UseToolCountsOptions {
  /** Skip the request — for a view with no card that would show a number. */
  enabled?: boolean;
  staleTime?: number;
}

/** The wire shape keys initiatives as strings; read them back as numbers. */
const toCountMap = (counts: Record<string, number> | undefined): Map<number, number> => {
  const map = new Map<number, number>();
  for (const [initiativeId, count] of Object.entries(counts ?? {})) {
    map.set(Number(initiativeId), count);
  }
  return map;
};

export function useToolCountsByInitiative(options?: UseToolCountsOptions): ToolCountsByInitiative {
  const guildId = useActiveGuildId();
  const query = useQuery({
    queryKey: getGetToolCountsByInitiativeApiV1CGuildIdToolsCountsByInitiativeGetQueryKey(guildId),
    queryFn: () => getToolCountsByInitiativeApiV1CGuildIdToolsCountsByInitiativeGet(guildId),
    enabled: options?.enabled ?? true,
    staleTime: options?.staleTime ?? 30_000,
  });

  // One small map per tool, built during render rather than memoized against
  // a query result that changes identity on its own.
  const byTool = {} as ToolCountsByInitiative;
  for (const tool of TOOLS) {
    byTool[tool] = { counts: toCountMap(query.data?.counts[tool]), isLoading: query.isLoading };
  }
  return byTool;
}

/** One tool's page: how many rows sit in each view, and the tag tree beside
 *  the view named by `params.view`. The previous answer stays on screen while
 *  the next view's arrives, so the badges do not blank out. */
export const useToolCounts = (
  tool: Tool,
  params: GetToolCountsApiV1CGuildIdToolsToolCountsGetParams
) => {
  const guildId = useActiveGuildId();
  return useQuery<ToolCountsResponse>({
    queryKey: getGetToolCountsApiV1CGuildIdToolsToolCountsGetQueryKey(guildId, tool, params),
    queryFn: () => getToolCountsApiV1CGuildIdToolsToolCountsGet(guildId, tool, params),
    placeholderData: keepPreviousData,
  });
};
