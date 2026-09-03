/**
 * The guild front page: pick a tool from the rail, see everything of that kind
 * in the guild underneath it.
 *
 * Both the rail and the table are tool-agnostic — the rail renders whatever the
 * tool registry declares (minus what this user can't see anywhere), and the
 * table renders whatever rows `useGuildToolRows` produces. Adding a tool adds
 * a circle and a set of rows, and nothing here.
 *
 * It is also the guild's initiative list — the standalone initiatives page was
 * folded into it. The section under the table holds the ones you're in and the
 * ones you could join, plus the create affordance for a guild admin, and it
 * takes the page over entirely for a member who is not yet in any initiative,
 * for whom every other section is empty by construction.
 */

import { useNavigate, useSearch } from "@tanstack/react-router";
import { Loader2 } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { GuildBannerBadges } from "@/components/guildHome/GuildBannerBadges";
import { GuildHomeEmptyState } from "@/components/guildHome/GuildHomeEmptyState";
import { GuildRecentComments } from "@/components/guildHome/GuildRecentComments";
import { InitiativeDirectory } from "@/components/guildHome/InitiativeDirectory";
import { CreateInitiativeDialog } from "@/components/initiatives/CreateInitiativeDialog";
import { PageBanner } from "@/components/PageBanner";
import { TOOL_TRAY_SURFACE, ToolRail } from "@/components/toolBrowser/ToolRail";
import { isToolSortField, type ToolSortField, ToolTable } from "@/components/toolBrowser/ToolTable";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useGuilds } from "@/hooks/useGuilds";
import { useGuildToolRows } from "@/hooks/useGuildToolRows";
import { useInitiativeAccess } from "@/hooks/useInitiativeAccess";
import { useInitiativeDirectory, useInitiatives } from "@/hooks/useInitiatives";
import { renderableBanner } from "@/lib/banner";
import { useGuildPath } from "@/lib/guildUrl";
import { CORE_TOOLS, TOOLS, toolForRouteSegment } from "@/lib/tools";
import { cn } from "@/lib/utils";

const DEFAULT_PAGE_SIZE = 20;

export function GuildHomePage() {
  const { t } = useTranslation("guildHome");
  const { activeGuild } = useGuilds();
  const gp = useGuildPath();
  const navigate = useNavigate();
  const search = useSearch({ strict: false }) as {
    tool?: string;
    page?: number;
    create?: string;
    q?: string;
    sort?: string;
    dir?: string;
  };

  const initiativesQuery = useInitiatives();
  const directoryQuery = useInitiativeDirectory();
  const directoryEntries = directoryQuery.data ?? [];
  const { filterVisible, permissionsFor, isGuildAdmin } = useInitiativeAccess();

  // Creating an initiative is guild-admin only (the backend enforces it), and
  // the affordance is threaded down as a callback: passing one IS the gate.
  const canCreateInitiatives = Boolean(activeGuild && isGuildAdmin);
  const [createDialogOpen, setCreateDialogOpen] = useState(false);
  const openCreateDialog = useCallback(() => setCreateDialogOpen(true), []);
  const onCreate = canCreateInitiatives ? openCreateDialog : undefined;

  // `?create=true` opens the dialog once — the deep link the sidebar and the
  // retired initiatives page both point at. Consumed once so dismissing the
  // dialog doesn't reopen it on the next render.
  const lastConsumedCreate = useRef<string>("");
  useEffect(() => {
    const shouldCreate = search.create === "true";
    const paramKey = `${shouldCreate}`;
    if (shouldCreate && paramKey !== lastConsumedCreate.current) {
      lastConsumedCreate.current = paramKey;
      setCreateDialogOpen(true);
    }
  }, [search.create]);

  const visibleInitiatives = useMemo(
    () => filterVisible(initiativesQuery.data),
    [initiativesQuery.data, filterVisible]
  );

  // Nothing to browse: the tool rail and table would be six empty circles over
  // an empty table, so the page becomes the story of how to get in instead.
  // Only an answered query can say "none" — a failed or still-arriving one is
  // absence of news, and telling someone they're in nothing on that basis
  // would be a lie the page states confidently.
  const hasNoInitiatives = initiativesQuery.isSuccess && visibleInitiatives.length === 0;

  // A tool earns its circle by being viewable in at least one initiative the
  // user can see. Before that list lands (or in a guild with no initiatives
  // yet) fall back to the always-on core tools rather than an empty rail.
  const tools = useMemo(() => {
    if (visibleInitiatives.length === 0) {
      return TOOLS.filter((tool) => CORE_TOOLS.has(tool));
    }
    return TOOLS.filter((tool) =>
      visibleInitiatives.some((initiative) => permissionsFor(initiative)[tool].view)
    );
  }, [visibleInitiatives, permissionsFor]);

  const requested = search.tool ? toolForRouteSegment(search.tool) : null;
  // An unknown or unreachable `?tool=` falls back to the first circle rather
  // than rendering a table the user has no business seeing.
  const selected = requested && tools.includes(requested) ? requested : (tools[0] ?? Tool.project);

  const page = search.page ?? 1;
  const setSearch = useCallback(
    (next: { page?: number; q?: string; sort?: string; dir?: string }) => {
      void navigate({
        to: ".",
        search: { ...search, ...next },
        replace: true,
      });
    },
    [navigate, search]
  );

  // The search text and the order are in the address, like the tool and the
  // page: a narrowed table is a link someone can send. The default order is
  // left out of it — most-recently-updated is what the endpoints do unasked,
  // so spelling it in every URL would only be noise.
  const query = search.q ?? "";
  const sortBy: ToolSortField = isToolSortField(search.sort) ? search.sort : "updated_at";
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
  // Switching tools is a fresh list: the rail's link carries no `q`, so the
  // box empties with it and a keystroke still waiting from the last tool is
  // dropped rather than landing on the new one.
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

  const { rows, totalCount, isLoading, isError } = useGuildToolRows(selected, page, pageSize, {
    search: query || undefined,
    sortBy,
    sortDir,
  });

  const pageCount = pageSize > 0 ? Math.max(1, Math.ceil(totalCount / pageSize)) : 1;
  // A bookmarked page outlives the rows it pointed at, and a hand-typed one
  // may never have had any. Either way the guild still holds items, so land
  // back on the first page instead of showing an empty table over them.
  useEffect(() => {
    if (!isLoading && totalCount > 0 && page > pageCount) {
      setSearch({ page: undefined });
    }
  }, [isLoading, totalCount, page, pageCount, setSearch]);

  // Every guild has a banner — the artwork it uploaded, or the colour it wears
  // instead — so this is the guild's header rather than a decoration it might
  // be without. A guild with no artwork gets a short band, not a hero.
  const banner = renderableBanner(activeGuild?.banner);

  // A faded banner is extended past where it would have ended, and the page's
  // own content is pulled back over the tail — so everything below the banner
  // needs to be positioned to paint over it, which a plain block would not.
  return (
    <div className="space-y-6">
      <PageBanner
        banner={banner}
        title={activeGuild?.name ?? t("title")}
        subtitle={activeGuild?.description ?? t("subtitle")}
        badges={
          activeGuild ? (
            <GuildBannerBadges
              memberCount={activeGuild.member_count}
              onlineCount={activeGuild.online_count}
              ink={banner.text_color}
            />
          ) : null
        }
      />

      <div className="relative z-10 space-y-6">
        {hasNoInitiatives ? (
          <GuildHomeEmptyState
            guildDescription={activeGuild?.description}
            entries={directoryEntries}
            directoryStatus={
              directoryQuery.isSuccess ? "success" : directoryQuery.isError ? "error" : "pending"
            }
            onCreate={onCreate}
          />
        ) : (
          <>
            {/* The rail and the table are one tray: the circles are its top
                edge rising, and everything a tool has to say sits in the same
                surface underneath them. Whatever the table is doing —
                arriving, failing, empty — happens in there, so the edge the
                circles melt into is always the thing they melt into. */}
            <div>
              <ToolRail
                tools={tools}
                selected={selected}
                to={gp("/")}
                label={t("toolRail")}
                align={banner.text_align}
              />
              <div
                className={cn("rounded-b-2xl px-3 pt-1 pb-3 sm:px-4 sm:pb-4", TOOL_TRAY_SURFACE)}
              >
                {/* A search that found nothing still renders the table: the
                    box that found nothing is in its toolbar, and taking it
                    away would leave no way to unsay the search. */}
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
                      <CardDescription>{t("empty.description")}</CardDescription>
                    </CardHeader>
                  </Card>
                ) : (
                  <ToolTable
                    tool={selected}
                    rows={rows}
                    initiatives={initiativesQuery.data ?? []}
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
                  />
                )}
              </div>
            </div>

            {/* The guild's initiative list, which is also its discovery surface:
              the ones you're in, then the ones you could join. */}
            <InitiativeDirectory entries={directoryEntries} onCreate={onCreate} />

            {/* Guild-wide, so it stays put as the rail switches the table's tool. */}
            <GuildRecentComments />
          </>
        )}

        {canCreateInitiatives ? (
          <CreateInitiativeDialog open={createDialogOpen} onOpenChange={setCreateDialogOpen} />
        ) : null}
      </div>
    </div>
  );
}
