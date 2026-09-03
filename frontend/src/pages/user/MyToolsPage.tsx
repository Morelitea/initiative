/**
 * My Tools: the community front page with the community boundary taken off.
 *
 * Pick a tool from the rail, see everything of that kind that reaches you —
 * across every community you're in, not one at a time. It replaced the
 * separate My Projects and My Documents pages, which were the same table twice
 * for two of the six tools.
 *
 * Two things are its own, and the rest is shared with the community front page
 * (the rail, the table, the row builder):
 *
 * - **A tab only appears for a tool you have something of.** `/me/tools/counts`
 *   answers for all six in one request; a reader who has never touched a queue
 *   is not offered an empty queue table.
 * - **Two views of the same list.** "Everything" is what reaches you — what was
 *   shared with you, with a role you hold, or with an initiative you're in.
 *   "Made by me" is what you wrote. The toggle is in the address, like the
 *   tool, the page and the order, so either view is a link.
 */

import { useQueries } from "@tanstack/react-query";
import { useNavigate, useSearch } from "@tanstack/react-router";
import { Loader2 } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import type { InitiativeRead } from "@/api/generated/initiativeAPI.schemas";
import { Tool } from "@/api/generated/initiativeAPI.schemas";
import {
  getListInitiativesApiV1GGuildIdInitiativesGetQueryKey,
  listInitiativesApiV1GGuildIdInitiativesGet,
} from "@/api/generated/initiatives/initiatives";
import { TOOL_TRAY_SURFACE, ToolRail } from "@/components/toolBrowser/ToolRail";
import {
  CROSS_GUILD_TOOL_SORT_FIELDS,
  isToolSortField,
  type ToolSortField,
  ToolTable,
} from "@/components/toolBrowser/ToolTable";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { MultiSelect } from "@/components/ui/multi-select";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { useGuilds } from "@/hooks/useGuilds";
import { toolsWithContent, useMyToolCounts, useMyToolRows } from "@/hooks/useMyTools";
import { toolForRouteSegment } from "@/lib/tools";
import { cn } from "@/lib/utils";

const DEFAULT_PAGE_SIZE = 20;
const ROUTE = "/my-tools";

/** The address bar's `communities=1,2` as ids, dropping anything unreadable. */
const parseCommunities = (raw: string | undefined): number[] =>
  (raw ?? "")
    .split(",")
    .map(Number)
    .filter((id) => Number.isFinite(id) && id > 0);

export function MyToolsPage() {
  const { t } = useTranslation("myTools");
  const { guilds } = useGuilds();
  const navigate = useNavigate();
  const search = useSearch({ strict: false }) as {
    tool?: string;
    page?: number;
    q?: string;
    sort?: string;
    dir?: string;
    made?: string;
    communities?: string;
  };

  const setSearch = useCallback(
    (next: Record<string, string | number | undefined>) => {
      void navigate({ to: ".", search: { ...search, ...next }, replace: true });
    },
    [navigate, search]
  );

  // "Made by me" is the narrower of the two views, so it is the one the address
  // has to say; a bare /my-tools is everything.
  const createdByMe = search.made === "me";
  const guildFilters = useMemo(() => parseCommunities(search.communities), [search.communities]);

  // Which tabs exist. The counts follow the view — the made-by-me list of a
  // tool you have never authored is empty, and a tab onto an empty table is
  // the thing this page is meant to avoid — but not the community filter:
  // narrowing the table should not make the reader's tools come and go.
  const countsQuery = useMyToolCounts({ created_by_me: createdByMe || undefined });
  const tools = useMemo(() => toolsWithContent(countsQuery.data), [countsQuery.data]);

  const requested = search.tool ? toolForRouteSegment(search.tool) : null;
  // An unknown or unreachable `?tool=` falls back to the first tab rather than
  // rendering a table the reader has nothing in.
  const selected = requested && tools.includes(requested) ? requested : (tools[0] ?? Tool.project);

  const page = search.page ?? 1;
  const query = search.q ?? "";
  const sortBy: ToolSortField = isToolSortField(search.sort, CROSS_GUILD_TOOL_SORT_FIELDS)
    ? search.sort
    : "updated_at";
  const sortDir: "asc" | "desc" =
    search.dir === "asc" || search.dir === "desc"
      ? search.dir
      : sortBy === "updated_at"
        ? "desc"
        : "asc";

  // What is typed goes into the box at once and to the server a beat later, so
  // a search is one request rather than one per keystroke.
  const [draftQuery, setDraftQuery] = useState(query);
  const lastPushedQuery = useRef(query);
  useEffect(() => {
    // A query that changed elsewhere — the back button, a pasted link — wins
    // over a draft nobody is typing into.
    if (query !== lastPushedQuery.current) {
      lastPushedQuery.current = query;
      setDraftQuery(query);
    }
  }, [query]);
  // Switching tools is a fresh list: the rail's link carries no `q`, so the box
  // empties with it and a keystroke still in flight is dropped rather than
  // landing on the new tool.
  const lastTool = useRef(selected);
  useEffect(() => {
    if (lastTool.current === selected) return;
    lastTool.current = selected;
    lastPushedQuery.current = query;
    setDraftQuery(query);
  }, [selected, query]);
  useEffect(() => {
    if (draftQuery === query) return;
    const timer = setTimeout(() => {
      lastPushedQuery.current = draftQuery;
      setSearch({ q: draftQuery || undefined, page: undefined });
    }, 300);
    return () => clearTimeout(timer);
  }, [draftQuery, query, setSearch]);

  const handleSortChange = useCallback(
    (field: ToolSortField, direction: "asc" | "desc") => {
      const isDefault = field === "updated_at" && direction === "desc";
      setSearch({
        sort: isDefault ? undefined : field,
        dir: isDefault ? undefined : direction,
        page: undefined,
      });
    },
    [setSearch]
  );

  // Page size is a view preference, not a URL concern — the `page` param stays
  // shareable while the size stays local, as on the other list pages.
  const [pageSize, setPageSize] = useState(DEFAULT_PAGE_SIZE);
  const handlePageSizeChange = useCallback(
    (size: number) => {
      setPageSize(size);
      setSearch({ page: undefined });
    },
    [setSearch]
  );

  const { rows, totalCount, isLoading, isError } = useMyToolRows(selected, page, pageSize, {
    guildIds: guildFilters,
    search: query || undefined,
    createdByMe,
    sortBy,
    sortDir,
  });

  const pageCount = pageSize > 0 ? Math.max(1, Math.ceil(totalCount / pageSize)) : 1;
  // A bookmarked page outlives the rows it pointed at. There are still rows, so
  // land back on the first page rather than showing an empty table over them.
  useEffect(() => {
    if (!isLoading && totalCount > 0 && page > pageCount) {
      setSearch({ page: undefined });
    }
  }, [isLoading, totalCount, page, pageCount, setSearch]);

  const communities = useMemo(
    () => new Map(guilds.map((guild) => [guild.id, guild.name])),
    [guilds]
  );

  // The initiative column names a row's initiative, and each community answers
  // for its own. Only the communities on this page of rows are asked, and the
  // answers are the same cache entries the sidebar and the community pages
  // already fill.
  const rowGuildIds = useMemo(
    () => [...new Set(rows.map((row) => row.guildId))].sort((a, b) => a - b),
    [rows]
  );
  const initiatives = useQueries({
    queries: rowGuildIds.map((guildId) => ({
      queryKey: getListInitiativesApiV1GGuildIdInitiativesGetQueryKey(guildId),
      queryFn: () => listInitiativesApiV1GGuildIdInitiativesGet(guildId),
      staleTime: 60_000,
    })),
    // `combine` rather than a `useMemo` over the results: the results array is
    // a fresh identity every render, so a memo keyed on it would never hit and
    // the table's columns would rebuild under it each time.
    combine: (results): InitiativeRead[] => results.flatMap((result) => result.data ?? []),
  });

  const emptyDescription = createdByMe ? t("empty.descriptionMine") : t("empty.description");

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 sm:flex-row sm:flex-wrap sm:items-end sm:justify-between">
        <div>
          <h1 className="font-semibold text-3xl tracking-tight">{t("title")}</h1>
          <p className="text-muted-foreground">{t("subtitle")}</p>
        </div>

        <div className="flex flex-wrap items-end gap-4">
          {/* Only worth offering to somebody who is in more than one community
              — with a single one, the filter can only say what the page
              already says. */}
          {guilds.length > 1 ? (
            <div className="w-full sm:w-56">
              <Label
                htmlFor="my-tools-communities"
                className="mb-2 block font-medium text-muted-foreground text-xs"
              >
                {t("communities.label")}
              </Label>
              <MultiSelect
                selectedValues={guildFilters.map(String)}
                options={guilds.map((guild) => ({ value: String(guild.id), label: guild.name }))}
                onChange={(values) => {
                  const ids = values.map(Number).filter(Number.isFinite);
                  setSearch({
                    communities: ids.length > 0 ? ids.join(",") : undefined,
                    page: undefined,
                  });
                }}
                placeholder={t("communities.all")}
                emptyMessage={t("communities.none")}
              />
            </div>
          ) : null}

          <ToggleGroup
            type="single"
            variant="outline"
            value={createdByMe ? "mine" : "all"}
            aria-label={t("view.label")}
            // A segmented control has no "neither" state to fall into: an
            // attempt to unset the active half leaves it where it was.
            onValueChange={(value) => {
              if (!value) return;
              setSearch({ made: value === "mine" ? "me" : undefined, page: undefined });
            }}
          >
            <ToggleGroupItem value="all">{t("view.everything")}</ToggleGroupItem>
            <ToggleGroupItem value="mine">{t("view.createdByMe")}</ToggleGroupItem>
          </ToggleGroup>
        </div>
      </div>

      {countsQuery.isLoading ? (
        <div className="flex items-center gap-2 p-2 text-muted-foreground text-sm">
          <Loader2 className="h-4 w-4 animate-spin" />
          {t("loading")}
        </div>
      ) : tools.length === 0 ? (
        <Card>
          <CardHeader>
            <CardTitle>{t("noTools.title")}</CardTitle>
            <CardDescription>
              {createdByMe ? t("noTools.descriptionMine") : t("noTools.description")}
            </CardDescription>
          </CardHeader>
        </Card>
      ) : (
        // The rail and the table are one tray: the circles are its top edge
        // rising, and everything a tool has to say sits in the same surface
        // underneath them.
        <div>
          <ToolRail tools={tools} selected={selected} to={ROUTE} label={t("toolRail")} />
          <div className={cn("rounded-b-2xl px-3 pt-1 pb-3 sm:px-4 sm:pb-4", TOOL_TRAY_SURFACE)}>
            {/* A search that found nothing still renders the table: the box
                that found nothing is in its toolbar, and taking it away would
                leave no way to unsay the search. */}
            {isLoading ? (
              <div className="flex items-center gap-2 p-2 text-muted-foreground text-sm">
                <Loader2 className="h-4 w-4 animate-spin" />
                {t("loading")}
              </div>
            ) : isError ? (
              <p className="p-2 text-destructive text-sm">{t("loadError")}</p>
            ) : totalCount === 0 && !query ? (
              <Card>
                <CardHeader>
                  <CardTitle>{t("empty.title")}</CardTitle>
                  <CardDescription>{emptyDescription}</CardDescription>
                </CardHeader>
              </Card>
            ) : (
              <ToolTable
                tool={selected}
                rows={rows}
                initiatives={initiatives}
                communities={communities}
                totalCount={totalCount}
                page={page}
                pageCount={pageCount}
                pageSize={pageSize}
                onPageChange={(next) => setSearch({ page: next <= 1 ? undefined : next })}
                onPageSizeChange={handlePageSizeChange}
                search={draftQuery}
                onSearchChange={setDraftQuery}
                sortBy={sortBy}
                sortDir={sortDir}
                onSortChange={handleSortChange}
                sortFields={CROSS_GUILD_TOOL_SORT_FIELDS}
              />
            )}
          </div>
        </div>
      )}
    </div>
  );
}
