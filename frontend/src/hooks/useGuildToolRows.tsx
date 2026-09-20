/**
 * One guild-wide page of whatever tool the guild home is showing.
 *
 * The nine list endpoints already agree on a shape — `{ items, total_count,
 * has_next }` keyed by `page`/`page_size` — so this asks every tool the same
 * question at once and gates every one but the selected tool off. That keeps
 * the calls unconditional (hook rules) while exactly one request is in flight.
 * Which query lists a tool comes from `TOOL_HOOKS`, so a new tool joins this
 * table by existing rather than by being named here.
 *
 * Turning the answer into rows is `lib/toolRows`, shared with the cross-guild
 * twin of this hook (`useMyToolRows`), so both tables say the same thing about
 * a tool.
 */

import { keepPreviousData, useQueries } from "@tanstack/react-query";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";

import type { Tool } from "@/api/generated/initiativeAPI.schemas";
import { TOOL_HOOKS } from "@/hooks/toolHooks";
import { useActiveGuildId } from "@/hooks/useActiveGuildId";
import type { ToolRow } from "@/lib/toolRows";
import { buildToolRows, oneToolResponse } from "@/lib/toolRows";
import { TOOLS } from "@/lib/tools";

/** How the guild home's one table is narrowed and ordered, in the terms every
 *  tool's list endpoint accepts. */
export interface GuildToolQuery {
  /** Case-insensitive substring of the name, searched across the whole set. */
  search?: string;
  /** One of `name`, `initiative`, `updated_at`. */
  sortBy?: string;
  sortDir?: "asc" | "desc";
  /** `true` shows what has been archived instead of what is live. Every tool
   *  can be archived, and a calendar has no list page of its own, so this table
   *  is where some of them are found — and the only place they can be taken
   *  back out. */
  archived?: true;
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
    ...(view.archived ? { archived: true } : {}),
  };

  // Only the selected tool fetches; the rest stay observed but idle. The
  // selected one keeps the rows it already has while a new page, search or
  // order is in flight — otherwise the table (and the search box in its
  // toolbar) would be replaced by a loading line on every keystroke.
  //
  // One `useQueries` rather than a hook per tool: the list comes from the
  // registry, so it is the same length and the same order on every render.
  const results = useQueries({
    queries: TOOLS.map((candidate) => ({
      ...TOOL_HOOKS[candidate].listQuery(guildId, params),
      enabled: candidate === tool,
      placeholderData: keepPreviousData,
    })),
  });
  const query = results[TOOLS.indexOf(tool)];

  const rows = useMemo<ToolRow[]>(
    () => buildToolRows(tool, oneToolResponse(tool, query.data), t, guildId),
    [tool, query.data, t, guildId]
  );

  return {
    rows,
    totalCount: query.data?.total_count ?? 0,
    isLoading: query.isLoading,
    isError: query.isError,
  };
}
