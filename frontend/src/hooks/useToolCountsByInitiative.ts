/**
 * How much of each tool lives in each initiative, for every tool at once.
 *
 * Every tool exposes the same `counts-by-initiative` shape (initiative id →
 * count), so this calls all six hooks unconditionally (hook rules) behind one
 * shared `enabled` and keys the results by `Tool`. Callers then render whatever
 * the registry declares rather than naming tools by hand — a new tool shows up
 * in every consumer as soon as it has a counts endpoint, and the `Record<Tool,
 * …>` below fails to build until it does.
 *
 * Shaped after `useGuildToolRows`, which fans out over the same six tools.
 */

import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { useCalendarCountsByInitiative } from "@/hooks/useCalendars";
import { useCounterGroupCountsByInitiative } from "@/hooks/useCounters";
import { useDashboardCountsByInitiative } from "@/hooks/useDashboards";
import { useDocumentCountsByInitiative } from "@/hooks/useDocuments";
import { usePostCountsByInitiative } from "@/hooks/usePosts";
import { useProjectCountsByInitiative } from "@/hooks/useProjects";
import { useQueueCountsByInitiative } from "@/hooks/useQueues";
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

  const projects = useProjectCountsByInitiative(queryOptions);
  const documents = useDocumentCountsByInitiative(queryOptions);
  const queues = useQueueCountsByInitiative(queryOptions);
  const counterGroups = useCounterGroupCountsByInitiative(queryOptions);
  const calendars = useCalendarCountsByInitiative(queryOptions);
  const dashboards = useDashboardCountsByInitiative(queryOptions);
  const posts = usePostCountsByInitiative(queryOptions);

  // Exhaustive by construction: a new Tool member fails to compile here until
  // it names the query that counts it.
  const queries: Record<Tool, { data?: { counts: Record<string, number> }; isLoading: boolean }> = {
    [Tool.project]: projects,
    [Tool.document]: documents,
    [Tool.queue]: queues,
    [Tool.counter_group]: counterGroups,
    [Tool.calendar]: calendars,
    [Tool.dashboard]: dashboards,
    [Tool.post]: posts,
  };

  // One small map per tool, read during render only — cheap enough to rebuild
  // rather than memoize against query results that change identity on their own.
  return Object.fromEntries(
    TOOLS.map((tool) => [
      tool,
      { counts: toCountMap(queries[tool].data?.counts), isLoading: queries[tool].isLoading },
    ])
  ) as ToolCountsByInitiative;
}
