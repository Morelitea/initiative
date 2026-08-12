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
 * Disabled apps are hidden here and stay visible in guild settings, which is
 * where an admin turns them back on.
 */

import { Link } from "@tanstack/react-router";
import { Blocks, CalendarDays, ChevronDown, Plus } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { GuildAppRead } from "@/api/generated/initiativeAPI.schemas";
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
import { guildAppPath, useGuildApps } from "@/hooks/useGuildApps";
import { useGuildPath } from "@/lib/guildUrl";
import { cn } from "@/lib/utils";

/** One icon per mountable tool. Apps mount this build's own tools, so this maps
 *  the closed set rather than trusting anything a listing supplies. */
const TOOL_ICONS = { calendar: CalendarDays } as const;

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

  const apps = (appsQuery.data?.items ?? []).filter((app) => app.enabled);

  // Nothing installed and nothing this person could do about it: show nothing.
  // A member should see initiatives, not an empty shelf.
  if (!apps.length && !isGuildAdmin) return null;

  return (
    <Collapsible open={open} onOpenChange={onOpenChange}>
      <SidebarGroup>
        <SidebarGroupLabel className="flex items-center gap-2 py-2">
          <Blocks className="h-4 w-4" />
          <CollapsibleTrigger className="flex flex-1 items-center gap-2 text-left">
            <span className="flex-1">{t("apps:title")}</span>
            <ChevronDown
              className={cn("h-4 w-4 shrink-0 transition-transform", !open && "-rotate-90")}
              aria-hidden
            />
          </CollapsibleTrigger>
          {isGuildAdmin && (
            <Tooltip delayDuration={300}>
              <TooltipTrigger asChild>
                <Link
                  to={gp("/marketplace")}
                  search={{ kind: "app" }}
                  aria-label={t("apps:add")}
                  className="flex h-5 w-5 shrink-0 items-center justify-center rounded-sm hover:bg-accent"
                >
                  <Plus className="h-4 w-4" />
                </Link>
              </TooltipTrigger>
              <TooltipContent>{t("apps:add")}</TooltipContent>
            </Tooltip>
          )}
        </SidebarGroupLabel>

        <CollapsibleContent>
          <SidebarGroupContent>
            {apps.length ? (
              <SidebarMenu>
                {apps.map((app) => (
                  <AppEntry key={app.id} app={app} />
                ))}
              </SidebarMenu>
            ) : (
              <p className="px-4 py-2 text-muted-foreground text-sm">{t("apps:none")}</p>
            )}
          </SidebarGroupContent>
        </CollapsibleContent>
      </SidebarGroup>
    </Collapsible>
  );
}

function AppEntry({ app }: { app: GuildAppRead }) {
  const gp = useGuildPath();
  const path = guildAppPath(app);
  const Icon = TOOL_ICONS[app.tool as keyof typeof TOOL_ICONS] ?? Blocks;

  return (
    <SidebarMenuItem>
      <SidebarMenuButton asChild={Boolean(path)} size="sm">
        {path ? (
          <Link to={gp(path)}>
            <Icon className="h-4 w-4" />
            <span className="truncate">{app.name}</span>
          </Link>
        ) : (
          <span className="flex items-center gap-2">
            <Icon className="h-4 w-4" />
            <span className="truncate">{app.name}</span>
          </span>
        )}
      </SidebarMenuButton>
    </SidebarMenuItem>
  );
}
