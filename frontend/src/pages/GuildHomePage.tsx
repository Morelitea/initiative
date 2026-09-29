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

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { AppSettingsDialog } from "@/components/apps/AppSettingsDialog";
import { GuildBannerBadges } from "@/components/guildHome/GuildBannerBadges";
import { GuildHomeEmptyState } from "@/components/guildHome/GuildHomeEmptyState";
import { GuildRecentComments } from "@/components/guildHome/GuildRecentComments";
import { InitiativeDirectory } from "@/components/guildHome/InitiativeDirectory";
import { CreateInitiativeWizard } from "@/components/initiatives/CreateInitiativeWizard";
import {
  archivedParam,
  isToolArchiveState,
  ToolArchiveFilter,
  type ToolArchiveState,
} from "@/components/initiativeTools/shared/ToolArchiveFilter";
import { PageBanner } from "@/components/PageBanner";
import { SkeletonRegion, TableSkeleton } from "@/components/skeletons/PageSkeletons";
import { TOOL_TRAY_SURFACE, ToolRail } from "@/components/toolBrowser/ToolRail";
import { ToolTable } from "@/components/toolBrowser/ToolTable";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useGuilds } from "@/hooks/useGuilds";
import { useGuildToolRows } from "@/hooks/useGuildToolRows";
import { liveInitiatives, useInitiativeAccess } from "@/hooks/useInitiativeAccess";
import { useInitiativeDirectory, useInitiatives } from "@/hooks/useInitiatives";
import { useToolBrowserSearch } from "@/hooks/useToolBrowserSearch";
import { renderableBanner } from "@/lib/banner";
import { useGuildPath } from "@/lib/guildUrl";
import { DEFAULT_ENABLED_TOOLS, TOOLS } from "@/lib/tools";
import { cn } from "@/lib/utils";

export function GuildHomePage() {
  const { t } = useTranslation("guildHome");
  const { activeGuild } = useGuilds();
  const gp = useGuildPath();
  const { search, setSearch, selectTool, query, table } = useToolBrowserSearch<{
    create?: string;
    state?: string;
    app?: number;
  }>();

  const initiativesQuery = useInitiatives();
  const directoryQuery = useInitiativeDirectory();
  const directoryEntries = directoryQuery.data ?? [];
  const { isGuildAdmin } = useInitiativeAccess();

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
    () => liveInitiatives(initiativesQuery.data),
    [initiativesQuery.data]
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
      return TOOLS.filter((tool) => DEFAULT_ENABLED_TOOLS.has(tool));
    }
    return TOOLS.filter((tool) =>
      visibleInitiatives.some((initiative) => initiative.can.view.includes(tool))
    );
  }, [visibleInitiatives]);

  const selected = selectTool(tools);
  // Which of the tool's two states the table is showing. In the address like
  // the rest of it, and left out while live — the default needs no spelling.
  const archiveState: ToolArchiveState = isToolArchiveState(search.state) ? search.state : "active";

  const { rows, totalCount, isLoading, isError } = useGuildToolRows(
    selected,
    table.page,
    table.pageSize,
    {
      search: query || undefined,
      sortBy: table.sortBy,
      sortDir: table.sortDir,
      archived: archivedParam(archiveState),
    }
  );

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
              guildId={activeGuild.id}
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
                {/* Which of the tool's two states the tray is showing. Above
                    the table rather than in its toolbar, because it changes
                    what the table IS rather than narrowing what it holds — and
                    for a calendar, which has no list page of its own, this is
                    the only place an archived one can be found. */}
                <div className="flex justify-end pt-2 pb-3">
                  <ToolArchiveFilter
                    tool={selected}
                    value={archiveState}
                    onChange={(next) =>
                      setSearch({
                        state: next === "active" ? undefined : next,
                        // The other state's cursor means nothing in this one.
                        page: undefined,
                      })
                    }
                  />
                </div>

                {/* A search that found nothing still renders the table: the
                    box that found nothing is in its toolbar, and taking it
                    away would leave no way to unsay the search. */}
                {isLoading ? (
                  <SkeletonRegion label={t("loading")}>
                    <TableSkeleton rows={5} columns={5} pagination />
                  </SkeletonRegion>
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
                    {...table}
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

        {/* `?app=` opens one app's settings where the reader answers what it
            asked to do as them — the link its notification carries. */}
        {search.app ? (
          <AppSettingsDialog
            appId={search.app}
            isGuildAdmin={isGuildAdmin}
            open
            onOpenChange={(next) => {
              if (!next) setSearch({ app: undefined });
            }}
          />
        ) : null}

        {canCreateInitiatives ? (
          <CreateInitiativeWizard
            open={createDialogOpen}
            onOpenChange={setCreateDialogOpen}
            // The community's first: the wizard has to say what an initiative
            // is before it asks for a name. Read off the whole list, not the
            // visible one — an admin sees everything, and an archived
            // initiative still means somebody has been here before.
            isFirst={initiativesQuery.isSuccess && (initiativesQuery.data?.length ?? 0) === 0}
          />
        ) : null}
      </div>
    </div>
  );
}
