/**
 * The My Tools page's data: one tool at a time, across every community the
 * reader belongs to.
 *
 * One `/me/*` list per tool, and one counts call. The lists are the guild-wide ones with
 * the guild boundary taken off — same rows, same filters, merged server-side —
 * so the rows they produce go through the same `lib/toolRows` builder the
 * community front page uses.
 */

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";

import type {
  CounterGroupListResponse,
  DashboardListResponse,
  MyToolCountsResponse,
  PostListResponse,
  QueueListResponse,
} from "@/api/generated/initiativeAPI.schemas";
import { Tool } from "@/api/generated/initiativeAPI.schemas";
import {
  getGetMyToolCountsApiV1MeToolsCountsGetQueryKey,
  getListMyCounterGroupsApiV1MeCounterGroupsGetQueryKey,
  getListMyDashboardsApiV1MeDashboardsGetQueryKey,
  getListMyPostsApiV1MePostsGetQueryKey,
  getListMyQueuesApiV1MeQueuesGetQueryKey,
  getMyToolCountsApiV1MeToolsCountsGet,
  listMyCounterGroupsApiV1MeCounterGroupsGet,
  listMyDashboardsApiV1MeDashboardsGet,
  listMyPostsApiV1MePostsGet,
  listMyQueuesApiV1MeQueuesGet,
} from "@/api/generated/my-tools/my-tools";
import { useMyCalendars } from "@/hooks/useCalendars";
import { useGlobalDocuments } from "@/hooks/useDocuments";
import { useGlobalProjects } from "@/hooks/useProjects";
import type { ToolResponses, ToolRow } from "@/lib/toolRows";
import { buildToolRows } from "@/lib/toolRows";
import { TOOLS } from "@/lib/tools";
import type { QueryOpts } from "@/types/query";

/**
 * What every `/me/{tool}` list takes. The six endpoints accept the same set —
 * that is what lets one table drive all of them — so the page builds one
 * params object rather than six.
 */
export interface MyToolListParams {
  guild_ids?: number[];
  search?: string;
  created_by_me?: boolean;
  sort_by?: string;
  sort_dir?: string;
  page?: number;
  page_size?: number;
}

/** How much of each tool reaches the reader — which tabs the page draws. */
export const useMyToolCounts = (
  params?: { guild_ids?: number[]; created_by_me?: boolean },
  options?: QueryOpts<MyToolCountsResponse>
) =>
  useQuery<MyToolCountsResponse>({
    queryKey: getGetMyToolCountsApiV1MeToolsCountsGetQueryKey(params),
    queryFn: () => getMyToolCountsApiV1MeToolsCountsGet(params),
    staleTime: 30_000,
    ...options,
  });

export const useMyQueues = (params?: MyToolListParams, options?: QueryOpts<QueueListResponse>) =>
  useQuery<QueueListResponse>({
    queryKey: getListMyQueuesApiV1MeQueuesGetQueryKey(params),
    queryFn: () => listMyQueuesApiV1MeQueuesGet(params),
    ...options,
  });

export const useMyCounterGroups = (
  params?: MyToolListParams,
  options?: QueryOpts<CounterGroupListResponse>
) =>
  useQuery<CounterGroupListResponse>({
    queryKey: getListMyCounterGroupsApiV1MeCounterGroupsGetQueryKey(params),
    queryFn: () => listMyCounterGroupsApiV1MeCounterGroupsGet(params),
    ...options,
  });

export const useMyDashboards = (
  params?: MyToolListParams,
  options?: QueryOpts<DashboardListResponse>
) =>
  useQuery<DashboardListResponse>({
    queryKey: getListMyDashboardsApiV1MeDashboardsGetQueryKey(params),
    queryFn: () => listMyDashboardsApiV1MeDashboardsGet(params),
    ...options,
  });

export const useMyPosts = (params?: MyToolListParams, options?: QueryOpts<PostListResponse>) =>
  useQuery<PostListResponse>({
    queryKey: getListMyPostsApiV1MePostsGetQueryKey(params),
    queryFn: () => listMyPostsApiV1MePostsGet(params),
    ...options,
  });

/** How the My Tools table is narrowed and ordered. */
export interface MyToolQuery {
  /** Communities to keep, or none for all of them. */
  guildIds?: number[];
  /** Case-insensitive match on the name, searched across the whole set. */
  search?: string;
  /** The page's other view: only what the reader wrote. */
  createdByMe?: boolean;
  /** One of `name`, `updated_at` — there is no cross-guild initiative order. */
  sortBy?: string;
  sortDir?: "asc" | "desc";
}

/**
 * One cross-guild page of whatever tool My Tools is showing.
 *
 * Twin of `useGuildToolRows`: all six lists are called so the hook order never
 * changes, and every one but the selected tool is gated off.
 */
export function useMyToolRows(tool: Tool, page: number, pageSize: number, view: MyToolQuery = {}) {
  const { t } = useTranslation("guildHome");

  const params: MyToolListParams = {
    page,
    page_size: pageSize,
    ...(view.guildIds && view.guildIds.length > 0 ? { guild_ids: view.guildIds } : {}),
    ...(view.search ? { search: view.search } : {}),
    ...(view.createdByMe ? { created_by_me: true } : {}),
    ...(view.sortBy ? { sort_by: view.sortBy, sort_dir: view.sortDir ?? "asc" } : {}),
  };
  const only = (candidate: Tool) => ({
    enabled: candidate === tool,
    placeholderData: keepPreviousData,
  });

  const projects = useGlobalProjects(params, only(Tool.project));
  const documents = useGlobalDocuments(params, only(Tool.document));
  const queues = useMyQueues(params, only(Tool.queue));
  const counterGroups = useMyCounterGroups(params, only(Tool.counter_group));
  const calendars = useMyCalendars(params, only(Tool.calendar));
  const dashboards = useMyDashboards(params, only(Tool.dashboard));
  const posts = useMyPosts(params, only(Tool.post));

  // Exhaustive by construction: a new Tool member fails to compile here until
  // it names the cross-guild query that lists it.
  const query = {
    [Tool.project]: projects,
    [Tool.document]: documents,
    [Tool.queue]: queues,
    [Tool.counter_group]: counterGroups,
    [Tool.calendar]: calendars,
    [Tool.dashboard]: dashboards,
    [Tool.post]: posts,
  }[tool];

  const rows = useMemo<ToolRow[]>(() => {
    const responses: ToolResponses = {
      [Tool.project]: projects.data,
      [Tool.document]: documents.data,
      [Tool.queue]: queues.data,
      [Tool.counter_group]: counterGroups.data,
      [Tool.calendar]: calendars.data,
      [Tool.dashboard]: dashboards.data,
      [Tool.post]: posts.data,
    };
    // Every row across communities carries its own guild id, so there is no
    // community for a fallback to stand in for.
    return buildToolRows(tool, responses, t, 0);
  }, [
    tool,
    t,
    projects.data,
    documents.data,
    queues.data,
    counterGroups.data,
    calendars.data,
    dashboards.data,
    posts.data,
  ]);

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
