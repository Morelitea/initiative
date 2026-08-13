/**
 * The guild's installed apps, above its initiatives.
 *
 * Apps are guild-wide surfaces, so they sit above the initiatives rather than
 * inside any of them. What shows depends on who is looking:
 *
 * - **No apps, ordinary member** — nothing at all. An empty section would be a
 *   promise of something they cannot act on.
 * - **No apps, guild admin** — the section with a `+`, the same invitation the
 *   initiatives list makes when a guild has none.
 * - **Apps installed** — one entry each, for everyone. Whether a member may do
 *   anything *inside* one is that instance's own sharing, enforced where the
 *   content lives.
 *
 * The exception is an app the server marks admin-only, which members do not see
 * at all: it has no sharing to widen, so an entry would refuse everyone who
 * clicked it. Which apps those are is the server's answer, not a kind the
 * sidebar interprets.
 *
 * Disabled apps are hidden here and stay visible in guild settings, which is
 * where an admin turns them back on. So are apps whose service is not set up on
 * this server — an entry that opens nothing is worse than no entry, and guild
 * settings is where that state is explained.
 *
 * **Every entry does something.** An app with a surface opens it; an app with
 * only a credential to supply opens that form where it stands, because "set up
 * my GitHub account" is the app, not a detour through settings. An app that is
 * neither — one contributing widgets or data to somewhere else — has nothing to
 * open, so it sits under a "show more" rather than spending a row on a click
 * that would go nowhere.
 */

import { Link } from "@tanstack/react-router";
import { Blocks, ChevronDown, ChevronsDownUp, ChevronsUpDown, Plus } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { GuildAppRead } from "@/api/generated/initiativeAPI.schemas";
import { AppSettingsDialog } from "@/components/apps/AppSettingsDialog";
import { Button } from "@/components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import {
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
} from "@/components/ui/sidebar";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { useGuildApps } from "@/hooks/useGuildApps";
import { appHasConnections, guildAppPath } from "@/lib/appSurfaces";
import { useGuildPath } from "@/lib/guildUrl";
import { cn } from "@/lib/utils";

export interface AppsSectionProps {
  isGuildAdmin: boolean;
  /** Persisted open/closed state, keyed like the other sidebar sections. */
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function AppsSection({ isGuildAdmin, open, onOpenChange }: AppsSectionProps) {
  const { t } = useTranslation(["apps", "nav"]);
  const gp = useGuildPath();
  const appsQuery = useGuildApps();
  const [showInert, setShowInert] = useState(false);

  // `available` is false when an app's service is not set up on this server, or
  // the operator switched it off: there is nothing behind the entry, so it does
  // not appear. Guild settings still lists it, which is where that is said.
  const apps = (appsQuery.data?.items ?? []).filter(
    (app) => app.enabled && app.available !== false
  );

  // An app with somewhere to go leads; one with nothing to open waits under
  // "show more" so a guild that installs many widget providers still has a
  // readable sidebar.
  const actionable = apps.filter(
    (app) => guildAppPath(app) !== null || appHasConnections(app.definition)
  );
  const inert = apps.filter((app) => !actionable.includes(app));

  // Nothing installed and nothing this person could do about it: show nothing.
  // A member should see initiatives, not an empty shelf.
  if (!apps.length && !isGuildAdmin) return null;

  return (
    <Collapsible open={open} onOpenChange={onOpenChange}>
      <SidebarGroup>
        <SidebarGroupLabel className="flex items-center gap-2 py-2">
          <Blocks className="h-4 w-4" />
          <CollapsibleTrigger className="flex flex-1 items-center text-left">
            <span className="flex-1">{t("apps:title")}</span>
          </CollapsibleTrigger>
          {apps.length > 0 && (
            <Tooltip delayDuration={300}>
              <TooltipTrigger asChild>
                <CollapsibleTrigger asChild>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-5 w-5 shrink-0"
                    aria-label={open ? t("nav:collapseAll") : t("nav:expandAll")}
                  >
                    {open ? (
                      <ChevronsDownUp className="h-3.5 w-3.5" />
                    ) : (
                      <ChevronsUpDown className="h-3.5 w-3.5" />
                    )}
                  </Button>
                </CollapsibleTrigger>
              </TooltipTrigger>
              <TooltipContent side="bottom">
                <p>{open ? t("nav:collapseAll") : t("nav:expandAll")}</p>
              </TooltipContent>
            </Tooltip>
          )}
        </SidebarGroupLabel>

        <CollapsibleContent>
          <SidebarGroupContent>
            {apps.length ? (
              <SidebarMenu>
                {actionable.map((app) => (
                  <AppEntry key={app.id} app={app} isGuildAdmin={isGuildAdmin} />
                ))}
                {showInert &&
                  inert.map((app) => (
                    <AppEntry key={app.id} app={app} isGuildAdmin={isGuildAdmin} />
                  ))}
                {inert.length > 0 && (
                  <SidebarMenuItem>
                    <SidebarMenuButton
                      size="sm"
                      onClick={() => setShowInert((shown) => !shown)}
                      className="text-muted-foreground"
                    >
                      <ChevronDown
                        className={cn("h-4 w-4 transition-transform", !showInert && "-rotate-90")}
                        aria-hidden
                      />
                      <span className="truncate">
                        {showInert
                          ? t("apps:showFewer")
                          : t("apps:showMore", { count: inert.length })}
                      </span>
                    </SidebarMenuButton>
                  </SidebarMenuItem>
                )}
              </SidebarMenu>
            ) : (
              <p className="px-4 py-2 text-muted-foreground text-sm">{t("apps:none")}</p>
            )}

            {/* Last, below "show more" as well, so adding one is always in the
                same place — the same shape the initiatives list uses. */}
            {isGuildAdmin && (
              <SidebarMenu>
                <SidebarMenuItem>
                  <SidebarMenuButton asChild size="sm">
                    <Link to={gp("/marketplace")} search={{ kind: "app" }}>
                      <Plus className="h-4 w-4" />
                      <span>{t("apps:add")}</span>
                    </Link>
                  </SidebarMenuButton>
                </SidebarMenuItem>
              </SidebarMenu>
            )}
          </SidebarGroupContent>
        </CollapsibleContent>
      </SidebarGroup>
    </Collapsible>
  );
}

function AppEntry({ app, isGuildAdmin }: { app: GuildAppRead; isGuildAdmin: boolean }) {
  const gp = useGuildPath();
  const [settingsOpen, setSettingsOpen] = useState(false);
  const path = guildAppPath(app);
  // The listing's own artwork, small. Every listing has one — a listing that
  // ships none is published with the app's own mark — so there is nothing to
  // fall back to.
  const icon = app.avatar_url ? (
    <img
      src={app.avatar_url}
      alt=""
      aria-hidden
      className="h-4 w-4 shrink-0 rounded-sm object-cover"
      loading="lazy"
    />
  ) : (
    <Blocks className="h-4 w-4" />
  );

  if (path) {
    return (
      <SidebarMenuItem>
        <SidebarMenuButton asChild size="sm">
          <Link to={gp(path)}>
            {icon}
            <span className="truncate">{app.name}</span>
          </Link>
        </SidebarMenuButton>
      </SidebarMenuItem>
    );
  }

  // No surface, but something to connect: the form opens here rather than
  // sending the member to a settings page to find it.
  if (appHasConnections(app.definition)) {
    return (
      <SidebarMenuItem>
        <SidebarMenuButton size="sm" onClick={() => setSettingsOpen(true)}>
          {icon}
          <span className="truncate">{app.name}</span>
        </SidebarMenuButton>
        <AppSettingsDialog
          appId={app.id}
          isGuildAdmin={isGuildAdmin}
          open={settingsOpen}
          onOpenChange={setSettingsOpen}
        />
      </SidebarMenuItem>
    );
  }

  return (
    <SidebarMenuItem>
      <SidebarMenuButton size="sm" className="cursor-default hover:bg-transparent">
        {icon}
        <span className="truncate">{app.name}</span>
      </SidebarMenuButton>
    </SidebarMenuItem>
  );
}
