/**
 * The guild front page: pick a tool from the rail, see everything of that kind
 * in the guild underneath it.
 *
 * Both the rail and the table are tool-agnostic — the rail renders whatever the
 * tool registry declares (minus what this user can't see anywhere), and the
 * table renders whatever rows `useGuildToolRows` produces. Adding a tool adds
 * a circle and a set of rows, and nothing here.
 */

import { useNavigate, useSearch } from "@tanstack/react-router";
import { Loader2 } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { GuildToolRail } from "@/components/guildHome/GuildToolRail";
import { GuildToolTable } from "@/components/guildHome/GuildToolTable";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useGuilds } from "@/hooks/useGuilds";
import { useGuildToolRows } from "@/hooks/useGuildToolRows";
import { useInitiativeAccess } from "@/hooks/useInitiativeAccess";
import { useInitiatives } from "@/hooks/useInitiatives";
import { TOOL_REGISTRY, TOOLS, toolForRouteSegment } from "@/lib/tools";

const DEFAULT_PAGE_SIZE = 20;

export function GuildHomePage() {
  const { t } = useTranslation("guildHome");
  const { activeGuild } = useGuilds();
  const navigate = useNavigate();
  const search = useSearch({ strict: false }) as { tool?: string; page?: number };

  const initiativesQuery = useInitiatives();
  const { filterVisible, permissionsFor } = useInitiativeAccess();

  // A tool earns its circle by being viewable in at least one initiative the
  // user can see. Before that list lands (or in a guild with no initiatives
  // yet) fall back to the always-on core tools rather than an empty rail.
  const tools = useMemo(() => {
    const visible = filterVisible(initiativesQuery.data);
    if (visible.length === 0) {
      return TOOLS.filter((tool) => TOOL_REGISTRY[tool].core);
    }
    return TOOLS.filter((tool) =>
      visible.some((initiative) => permissionsFor(initiative)[tool].view)
    );
  }, [initiativesQuery.data, filterVisible, permissionsFor]);

  const requested = search.tool ? toolForRouteSegment(search.tool) : null;
  // An unknown or unreachable `?tool=` falls back to the first circle rather
  // than rendering a table the user has no business seeing.
  const selected = requested && tools.includes(requested) ? requested : (tools[0] ?? Tool.project);

  const page = search.page ?? 1;
  const setSearch = useCallback(
    (next: { page?: number }) => {
      void navigate({
        to: ".",
        search: { ...search, ...next },
        replace: true,
      });
    },
    [navigate, search]
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

  const { rows, totalCount, isLoading, isError } = useGuildToolRows(selected, page, pageSize);

  const pageCount = pageSize > 0 ? Math.max(1, Math.ceil(totalCount / pageSize)) : 1;
  // A bookmarked page outlives the rows it pointed at, and a hand-typed one
  // may never have had any. Either way the guild still holds items, so land
  // back on the first page instead of showing an empty table over them.
  useEffect(() => {
    if (!isLoading && totalCount > 0 && page > pageCount) {
      setSearch({ page: undefined });
    }
  }, [isLoading, totalCount, page, pageCount, setSearch]);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="font-bold text-2xl tracking-tight md:text-3xl">
          {activeGuild?.name ?? t("title")}
        </h1>
        <p className="text-muted-foreground">{t("subtitle")}</p>
      </div>

      <GuildToolRail tools={tools} selected={selected} />

      {isLoading ? (
        <div className="flex items-center gap-2 text-muted-foreground text-sm">
          <Loader2 className="h-4 w-4 animate-spin" />
          {t("loading")}
        </div>
      ) : isError ? (
        <p className="text-destructive text-sm">{t("loadError")}</p>
      ) : totalCount === 0 ? (
        <Card>
          <CardHeader>
            <CardTitle>{t("empty.title")}</CardTitle>
            <CardDescription>{t("empty.description")}</CardDescription>
          </CardHeader>
        </Card>
      ) : (
        <GuildToolTable
          tool={selected}
          rows={rows}
          initiatives={initiativesQuery.data ?? []}
          totalCount={totalCount}
          page={page}
          pageCount={pageCount}
          pageSize={pageSize}
          onPageChange={(next) => setSearch({ page: next <= 1 ? undefined : next })}
          onPageSizeChange={handlePageSizeChange}
        />
      )}
    </div>
  );
}
