/**
 * One guild-wide page of whatever tool the guild home is showing.
 *
 * The six list endpoints already agree on a shape — `{ items, total_count,
 * has_next }` keyed by `page`/`page_size` — so this hook calls all six and
 * gates every one but the selected tool with `enabled: false`. That keeps the
 * calls unconditional (hook rules) while exactly one request is in flight.
 *
 * Turning the answer into rows is `lib/toolRows`, shared with the cross-guild
 * twin of this hook (`useMyToolRows`), so both tables say the same thing about
 * a tool.
 */

import { keepPreviousData } from "@tanstack/react-query";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";

import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { useActiveGuildId } from "@/hooks/useActiveGuildId";
import { useCalendarsList } from "@/hooks/useCalendars";
import { useCounterGroupsList } from "@/hooks/useCounters";
import { useDashboardsList } from "@/hooks/useDashboards";
import { useDocumentsList } from "@/hooks/useDocuments";
import { useProjects } from "@/hooks/useProjects";
import { useQueuesList } from "@/hooks/useQueues";
import type { ToolResponses, ToolRow } from "@/lib/toolRows";
import { buildToolRows } from "@/lib/toolRows";

export type { ToolRow as GuildToolRow } from "@/lib/toolRows";

/** How the guild home's one table is narrowed and ordered, in the terms every
 *  tool's list endpoint accepts. */
export interface GuildToolQuery {
  /** Case-insensitive substring of the name, searched across the whole set. */
  search?: string;
  /** One of `name`, `initiative`, `updated_at`. */
  sortBy?: string;
  sortDir?: "asc" | "desc";
}

export function useGuildToolRows(
  tool: Tool,
  page: number,
  pageSize: number,
  view: GuildToolQuery = {}
) {
  const { t } = useTranslation("guildHome");
  const guildId = useActiveGuildId();

  // Search and sort go to the server, not to the rows already in hand: the
  // table holds one page of a guild-wide list, and filtering that page would
  // answer "no matches" while the guild holds matches on page 4.
  const params = {
    page,
    page_size: pageSize,
    ...(view.search ? { search: view.search } : {}),
    ...(view.sortBy ? { sort_by: view.sortBy, sort_dir: view.sortDir ?? "asc" } : {}),
  };
  // Only the selected tool fetches; the rest stay mounted but idle. The
  // selected one keeps the rows it already has while a new page, search or
  // order is in flight — otherwise the table (and the search box in its
  // toolbar) would be replaced by a loading line on every keystroke.
  const only = (candidate: Tool) => ({
    enabled: candidate === tool,
    placeholderData: keepPreviousData,
  });

  const projects = useProjects(params, only(Tool.project));
  const documents = useDocumentsList(params, only(Tool.document));
  const queues = useQueuesList(params, only(Tool.queue));
  const counterGroups = useCounterGroupsList(params, only(Tool.counter_group));
  const calendars = useCalendarsList(params, only(Tool.calendar));
  const dashboards = useDashboardsList(params, only(Tool.dashboard));

  // Exhaustive by construction: a new Tool member fails to compile here until
  // it names the query that lists it.
  const query = {
    [Tool.project]: projects,
    [Tool.document]: documents,
    [Tool.queue]: queues,
    [Tool.counter_group]: counterGroups,
    [Tool.calendar]: calendars,
    [Tool.dashboard]: dashboards,
  }[tool];

  const rows = useMemo<ToolRow[]>(() => {
    const responses: ToolResponses = {
      [Tool.project]: projects.data,
      [Tool.document]: documents.data,
      [Tool.queue]: queues.data,
      [Tool.counter_group]: counterGroups.data,
      [Tool.calendar]: calendars.data,
      [Tool.dashboard]: dashboards.data,
    };
    return buildToolRows(tool, responses, t, guildId);
  }, [
    tool,
    t,
    guildId,
    projects.data,
    documents.data,
    queues.data,
    counterGroups.data,
    calendars.data,
    dashboards.data,
  ]);

  return {
    rows,
    totalCount: query.data?.total_count ?? 0,
    isLoading: query.isLoading,
    isError: query.isError,
  };
}
