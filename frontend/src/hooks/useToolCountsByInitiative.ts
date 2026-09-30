/**
 * How much of each tool lives in each initiative, for every tool at once.
 *
 * One request answers every tool (tool → initiative id → count), and the
 * result is spread over the registry's `TOOLS`, keyed by `Tool`. Callers then
 * render whatever the registry declares rather than naming tools by hand — a
 * new tool shows up in every consumer as soon as the server counts it.
 */

import { useQuery } from "@tanstack/react-query";

import type { Tool } from "@/api/generated/initiativeAPI.schemas";
import {
  getGetToolCountsByInitiativeApiV1CGuildIdToolsCountsByInitiativeGetQueryKey,
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
