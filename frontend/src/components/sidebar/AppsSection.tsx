/**
 * The guild's installed apps, above its initiatives.
 *
 * Apps are guild-wide surfaces, so they sit above the initiatives rather than
 * inside any of them. What shows depends on who is looking:
 *
 * - **Apps installed** — one entry each, for everyone. Whether a member may do
 *   anything *inside* one is that instance's own sharing, enforced where the
 *   content lives.
 * - **No apps** — the section still shows, for everyone. A member cannot add
 *   one, but they can look at what exists and ask for it, so the shelf is worth
 *   pointing at; what differs is the invitation at the bottom.
 *
 * A surface names the audience it is for, and an entry is only offered to a
 * reader who is in it — an app whose only guild-wide surface is for admins does
 * not take a row for a member. The mint settles the same question again under
 * the caller's own session; this is about not pointing at a closed door.
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
import { Blocks, ChevronDown, ChevronsDownUp, ChevronsUpDown, Plus, Store } from "lucide-react";
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
  // readable sidebar. A surface declared for the guild's admins is not
  // somewhere a member can go, so for them it does not count as one.
  const actionable = apps.filter(
    (app) => guildAppPath(app, { isGuildAdmin }) !== null || appHasConnections(app.definition)
  );
  const inert = apps.filter((app) => !actionable.includes(app));

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

            {/* Last, below "show more" as well, so it is always in the same
                place — the same shape the initiatives list uses. An admin adds
                one; everyone else browses the same shelf, where a listing says
                who to ask. */}
            <SidebarMenu>
              <SidebarMenuItem>
                <SidebarMenuButton asChild size="sm">
                  <Link to={gp("/marketplace")} search={{ kind: "app" }}>
                    {isGuildAdmin ? <Plus className="h-4 w-4" /> : <Store className="h-4 w-4" />}
                    <span>{isGuildAdmin ? t("apps:add") : t("apps:browse")}</span>
                  </Link>
                </SidebarMenuButton>
              </SidebarMenuItem>
            </SidebarMenu>
          </SidebarGroupContent>
        </CollapsibleContent>
      </SidebarGroup>
    </Collapsible>
  );
}

function AppEntry({ app, isGuildAdmin }: { app: GuildAppRead; isGuildAdmin: boolean }) {
  const gp = useGuildPath();
  const [settingsOpen, setSettingsOpen] = useState(false);
  const path = guildAppPath(app, { isGuildAdmin });
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
