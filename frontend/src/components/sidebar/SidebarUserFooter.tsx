import { Link } from "@tanstack/react-router";
import {
  ChartColumn,
  CircleQuestionMark,
  CircleUserRound,
  Settings,
  ShieldCheck,
  SquareCheckBig,
  UserCog,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import type { UserRead } from "@/api/generated/initiativeAPI.schemas";
import { ModeToggle } from "@/components/ModeToggle";
import { NotificationBell } from "@/components/notifications/NotificationBell";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
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
import { ProfileAvatar } from "@/components/user/ProfileAvatar";
import { VersionDialog } from "@/components/VersionDialog";
import { guildPath } from "@/lib/guildUrl";
import { getUrlHandle, getUserDisplayName } from "@/lib/userDisplay";

export interface SidebarUserFooterProps {
  /** The signed-in account, or null while it is still being fetched. */
  user: UserRead | null;
  isGuildAdmin: boolean;
  canManagePlatformConfig: boolean;
  canAccessAdminDashboard: boolean;
  activeGuildId: number | null;
  currentVersion: string;
  latestVersion: string | null;
  hasUpdate: boolean;
  isLoadingVersion: boolean;
  onLogout: () => void;
}

export const SidebarUserFooter = ({
  user,
  isGuildAdmin,
  canManagePlatformConfig,
  canAccessAdminDashboard,
  activeGuildId,
  currentVersion,
  latestVersion,
  hasUpdate,
  isLoadingVersion,
  onLogout,
}: SidebarUserFooterProps) => {
  const { t } = useTranslation(["nav"]);
  const gp = (path: string) => (activeGuildId ? guildPath(activeGuildId, path) : path);
  const displayName = getUserDisplayName(user);
  const handle = getUrlHandle(user);

  return (
    <SidebarFooter className="border-t border-r">
      <div className="flex flex-col">
        <div className="flex items-center gap-2 p-2">
          {/* modal={false}: a modal dropdown nested in the non-modal mobile
              sidebar drawer dismisses the drawer on open. Matches the
              notification-bell popover, which is non-modal and doesn't. */}
          <DropdownMenu modal={false}>
            <DropdownMenuTrigger asChild>
              <Button
                variant="ghost"
                className="h-auto min-w-0 flex-1 justify-start gap-2 px-2 py-2"
              >
                {/* Wearing the frame it is wearing on the profile: what you
                    picked is on you everywhere you appear, not only where the
                    picking happened. */}
                <ProfileAvatar
                  user={user}
                  decorations={user?.profile_decorations}
                  className="size-8 text-xs"
                />
                <div className="flex min-w-0 flex-1 flex-col items-start overflow-hidden text-left">
                  <span className="w-full truncate font-medium text-sm">{displayName}</span>
                </div>
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-56">
              <DropdownMenuLabel>{t("myAccount")}</DropdownMenuLabel>
              <DropdownMenuSeparator />
              {handle ? (
                <DropdownMenuItem asChild>
                  <Link to="/u/$handle" params={{ handle }}>
                    <CircleUserRound className="h-4 w-4" /> {t("myProfile")}
                  </Link>
                </DropdownMenuItem>
              ) : null}
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
              {canAccessAdminDashboard && (
                <DropdownMenuItem asChild>
                  <Link to="/settings/admin">
                    <ShieldCheck className="h-4 w-4" /> {t("adminDashboard")}
                  </Link>
                </DropdownMenuItem>
              )}
              {canManagePlatformConfig && (
                <DropdownMenuItem asChild>
                  <Link to="/settings/platform">
                    <Settings className="h-4 w-4" /> {t("platformSettings")}
                  </Link>
                </DropdownMenuItem>
              )}
              <DropdownMenuSeparator />
              <DropdownMenuItem onSelect={() => onLogout()}>{t("signOut")}</DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>

          <div className="flex shrink-0 items-center gap-1">
            {user ? <NotificationBell /> : null}
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
              <button type="button" className="flex cursor-pointer items-center gap-1.5">
                <span className="text-muted-foreground text-xs transition-colors hover:text-foreground">
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
                <a
                  href="https://morelitea.github.io/initiative/"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-muted-foreground transition-colors hover:text-foreground"
                  aria-label={t("viewDocumentation")}
                >
                  <CircleQuestionMark className="h-4 w-4" />
                </a>
              </TooltipTrigger>
              <TooltipContent side="top">
                <p>{t("viewDocumentation")}</p>
              </TooltipContent>
            </Tooltip>
          </div>
        </div>
      </div>
    </SidebarFooter>
  );
};
