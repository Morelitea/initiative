/**
 * How much of each tool lives in each initiative, for every tool at once.
 *
 * Every tool exposes the same `counts-by-initiative` shape (initiative id →
 * count), so this reads the one each declares in `TOOL_HOOKS` and runs the lot
 * behind one shared `enabled`, keyed by `Tool`. Callers then render whatever
 * the registry declares rather than naming tools by hand — a new tool shows up
 * in every consumer as soon as it has a counts endpoint, and the table it is
 * read from fails to build until it does.
 *
 * Shaped after `useGuildToolRows`, which fans out over the same tools.
 */

import { useQueries } from "@tanstack/react-query";

import type { Tool } from "@/api/generated/initiativeAPI.schemas";
import { TOOL_HOOKS } from "@/hooks/toolHooks";
import { useActiveGuildId } from "@/hooks/useActiveGuildId";
import { TOOLS } from "@/lib/tools";

/** One tool's counts, by initiative id. */
export interface ToolCounts {
  counts: Map<number, number>;
  isLoading: boolean;
}

export type ToolCountsByInitiative = Record<Tool, ToolCounts>;

export interface UseToolCountsOptions {
  /** Skip every request — for a view with no card that would show a number. */
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
  const queryOptions = {
    enabled: options?.enabled ?? true,
    staleTime: options?.staleTime ?? 30_000,
  };

  // One `useQueries` rather than a hook per tool: the list comes from the
  // registry, so it is the same length and the same order on every render, and
  // a tool joins the fan-out by existing.
  const guildId = useActiveGuildId();
  const results = useQueries({
    queries: TOOLS.map((tool) => ({ ...TOOL_HOOKS[tool].countsQuery(guildId), ...queryOptions })),
  });

  // One small map per tool, built during render rather than memoized against
  // query results that change identity on their own.
  const byTool = {} as ToolCountsByInitiative;
  TOOLS.forEach((tool, index) => {
    const query = results[index];
    byTool[tool] = { counts: toCountMap(query.data?.counts), isLoading: query.isLoading };
  });
  return byTool;
}
