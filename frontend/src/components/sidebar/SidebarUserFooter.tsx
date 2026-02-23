import { useMemo } from "react";
import { Link } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";
import { Settings, ChartColumn, SquareCheckBig, UserCog, Search } from "lucide-react";
import { SiGithub } from "@icons-pack/react-simple-icons";

import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Kbd } from "@/components/ui/kbd";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { SidebarFooter } from "@/components/ui/sidebar";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { VersionDialog } from "@/components/VersionDialog";
import { ModeToggle } from "@/components/ModeToggle";
import { NotificationBell } from "@/components/notifications/NotificationBell";
import { getOpenCommandCenter } from "@/components/CommandCenter";
import { guildPath } from "@/lib/guildUrl";

export interface SidebarUserFooterProps {
  userDisplayName: string;
  userEmail: string;
  userInitials: string;
  avatarSrc: string | null;
  isGuildAdmin: boolean;
  isPlatformAdmin: boolean;
  activeGuildId: number | null;
  hasUser: boolean;
  currentVersion: string;
  latestVersion: string | null;
  hasUpdate: boolean;
  isLoadingVersion: boolean;
  onLogout: () => void;
}

export const SidebarUserFooter = ({
  userDisplayName,
  userEmail,
  userInitials,
  avatarSrc,
  isGuildAdmin,
  isPlatformAdmin,
  activeGuildId,
  hasUser,
  currentVersion,
  latestVersion,
  hasUpdate,
  isLoadingVersion,
  onLogout,
}: SidebarUserFooterProps) => {
  const { t } = useTranslation(["nav", "command"]);
  const gp = (path: string) => (activeGuildId ? guildPath(activeGuildId, path) : path);

  const isMac = useMemo(
    () => typeof navigator !== "undefined" && /Mac|iPhone|iPad|iPod/.test(navigator.userAgent),
    []
  );
  const shortcutLabel = isMac ? "\u2318K" : "Ctrl+K";
  const isTouchDevice = useMemo(
    () => typeof window !== "undefined" && "ontouchstart" in window,
    []
  );

  return (
    <SidebarFooter className="border-t border-r">
      <div className="flex flex-col">
        <div className="flex items-center gap-2 p-2">
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                variant="ghost"
                className="h-auto min-w-0 flex-1 justify-start gap-2 px-2 py-2"
              >
                <Avatar className="h-8 w-8 shrink-0">
                  {avatarSrc ? <AvatarImage src={avatarSrc} alt={userDisplayName} /> : null}
                  <AvatarFallback className="text-xs">{userInitials}</AvatarFallback>
                </Avatar>
                <div className="flex min-w-0 flex-1 flex-col items-start overflow-hidden text-left">
                  <span className="w-full truncate text-sm font-medium">{userDisplayName}</span>
                  <span className="text-muted-foreground w-full truncate text-xs">{userEmail}</span>
                </div>
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-56">
              <DropdownMenuLabel>{t("myAccount")}</DropdownMenuLabel>
              <DropdownMenuSeparator />
              <DropdownMenuItem asChild>
                <Link to="/">
                  <SquareCheckBig className="h-4 w-4" /> {t("myTasks")}
                </Link>
              </DropdownMenuItem>
              <DropdownMenuItem asChild>
                <Link to="/user-stats">
                  <ChartColumn className="h-4 w-4" /> {t("myStats")}
                </Link>
              </DropdownMenuItem>
              <DropdownMenuItem asChild>
                <Link to="/profile">
                  <UserCog className="h-4 w-4" /> {t("userSettings")}
                </Link>
              </DropdownMenuItem>
              {isGuildAdmin && activeGuildId && (
                <DropdownMenuItem asChild>
                  <Link to={gp("/settings")}>
                    <Settings className="h-4 w-4" /> {t("guildSettings")}
                  </Link>
                </DropdownMenuItem>
              )}
              {isPlatformAdmin && (
                <DropdownMenuItem asChild>
                  <Link to="/settings/admin">
                    <Settings className="h-4 w-4" /> {t("platformSettings")}
                  </Link>
                </DropdownMenuItem>
              )}
              <DropdownMenuSeparator />
              <DropdownMenuItem onSelect={() => onLogout()}>{t("signOut")}</DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>

          <div className="flex shrink-0 items-center gap-1">
            {hasUser && <NotificationBell />}
            <ModeToggle />
          </div>
        </div>
        <div className="border-t">
          <div className="flex items-center justify-between px-3 py-2">
            <VersionDialog
              currentVersion={currentVersion}
              latestVersion={latestVersion}
              hasUpdate={hasUpdate}
              isLoadingVersion={isLoadingVersion}
            >
              <button className="flex cursor-pointer items-center gap-1.5">
                {/* eslint-disable-next-line i18next/no-literal-string */}
                <span className="text-muted-foreground hover:text-foreground text-xs transition-colors">
                  v{currentVersion}
                </span>
                {hasUpdate && (
                  <Badge variant="default" className="h-4 px-1.5 text-[10px]">
                    {t("newBadge")}
                  </Badge>
                )}
              </button>
            </VersionDialog>

            <Tooltip delayDuration={300}>
              <TooltipTrigger asChild>
                <button
                  onClick={() => getOpenCommandCenter()?.()}
                  className="text-muted-foreground hover:text-foreground flex items-center gap-1 transition-colors"
                  aria-label={t("command:shortcutHint")}
                >
                  {isTouchDevice ? <Search className="h-4 w-4" /> : <Kbd>{shortcutLabel}</Kbd>}
                </button>
              </TooltipTrigger>
              <TooltipContent side="top">
                <p>{t("command:shortcutTooltip", { shortcut: shortcutLabel })}</p>
              </TooltipContent>
            </Tooltip>

            <Tooltip delayDuration={300}>
              <TooltipTrigger asChild>
                <a
                  href="https://github.com/Morelitea/initiative"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-muted-foreground hover:text-foreground transition-colors"
                  aria-label={t("viewOnGitHub")}
                >
                  <SiGithub className="h-4 w-4" />
                </a>
              </TooltipTrigger>
              <TooltipContent side="top">
                <p>{t("viewOnGitHub")}</p>
              </TooltipContent>
            </Tooltip>
          </div>
        </div>
      </div>
    </SidebarFooter>
  );
};
