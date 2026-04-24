/**
 * Status badge component showing collaboration state and active collaborators.
 */

import { useTranslation } from "react-i18next";
import { Circle, CloudOff, RefreshCw, Users, Wifi, WifiOff } from "lucide-react";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { Badge } from "@/components/ui/badge";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { cn } from "@/lib/utils";
import { getInitials } from "@/lib/initials";
import { resolveUploadUrl } from "@/lib/uploadUrl";
import type { CollaboratorInfo } from "@/lib/yjs/CollaborationProvider";
import type { ConnectionStatus } from "@/hooks/useCollaboration";

export interface CollaborationStatusBadgeProps {
  connectionStatus: ConnectionStatus;
  collaborators: CollaboratorInfo[];
  isCollaborating: boolean;
  /** Whether the collaboration provider has synced with the server */
  isSynced?: boolean;
  /** Device-level network status. When false, overrides other states to show "Offline". */
  isOnline?: boolean;
  className?: string;
}

/**
 * Displays collaboration status and list of active collaborators.
 */
export function CollaborationStatusBadge({
  connectionStatus,
  collaborators,
  isCollaborating,
  isSynced = true,
  isOnline = true,
  className,
}: CollaborationStatusBadgeProps) {
  const { t } = useTranslation("documents");

  // When explicitly offline, always render regardless of collaborator count.
  // Otherwise keep the existing early-return so the badge stays hidden when
  // collaboration is disabled and nobody else is here.
  if (isOnline && connectionStatus === "disconnected" && collaborators.length === 0) {
    return null;
  }

  const statusConfig = {
    connecting: {
      icon: Wifi,
      label: t("collab.connecting"),
      color: "text-yellow-500",
      bgColor: "bg-yellow-100 dark:bg-yellow-900/20",
    },
    syncing: {
      icon: RefreshCw,
      label: t("collab.syncing"),
      color: "text-blue-500",
      bgColor: "bg-blue-100 dark:bg-blue-900/20",
    },
    connected: {
      icon: Users,
      label: t("collab.online"),
      color: "text-green-500",
      bgColor: "bg-green-100 dark:bg-green-900/20",
    },
    disconnected: {
      icon: WifiOff,
      label: t("collab.offline"),
      color: "text-muted-foreground",
      bgColor: "bg-muted",
    },
    error: {
      icon: CloudOff,
      label: t("collab.connectionError"),
      color: "text-red-500",
      bgColor: "bg-red-100 dark:bg-red-900/20",
    },
    offline: {
      icon: WifiOff,
      label: t("collab.networkOffline"),
      color: "text-amber-600 dark:text-amber-500",
      bgColor: "bg-amber-100 dark:bg-amber-900/20",
    },
  };

  // Offline overrides everything. Otherwise show syncing when connected but not yet synced.
  const effectiveStatus: keyof typeof statusConfig = !isOnline
    ? "offline"
    : connectionStatus === "connected" && !isSynced
      ? "syncing"
      : connectionStatus;

  const config = statusConfig[effectiveStatus];
  const StatusIcon = config.icon;

  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger asChild>
          <div className={cn("flex items-center gap-2", className)}>
            <Badge
              variant="outline"
              className={cn("gap-1.5 px-2 py-1 font-normal", config.bgColor)}
            >
              <StatusIcon className={cn("h-3 w-3", config.color)} />
              <span className="text-xs">{config.label}</span>
              {isOnline && isCollaborating && collaborators.length > 0 && (
                <span className="text-muted-foreground ml-0.5 text-xs">
                  ({collaborators.length})
                </span>
              )}
            </Badge>

            {/* Collaborator avatars */}
            {isOnline && isCollaborating && collaborators.length > 0 && (
              <div className="flex -space-x-2">
                {collaborators.slice(0, 4).map((collaborator, index) => (
                  <CollaboratorAvatar
                    key={collaborator.user_id}
                    collaborator={collaborator}
                    index={index}
                  />
                ))}
                {collaborators.length > 4 && (
                  <div className="bg-muted text-muted-foreground flex h-7 w-7 items-center justify-center rounded-full border-2 border-white text-xs font-medium dark:border-gray-800">
                    +{collaborators.length - 4}
                  </div>
                )}
              </div>
            )}
          </div>
        </TooltipTrigger>
        <TooltipContent side="bottom" className="bg-popover text-popover-foreground max-w-xs">
          <div className="space-y-2">
            <div className="flex items-center gap-2">
              <Circle className={cn("h-2 w-2 fill-current", config.color)} />
              <span className="font-medium">{config.label}</span>
            </div>
            {collaborators.length > 0 && (
              <div className="space-y-1">
                <p className="text-xs opacity-70">{t("collab.activeCollaborators")}</p>
                <ul className="space-y-1">
                  {collaborators.map((c) => (
                    <li key={c.user_id} className="flex items-center gap-2 text-sm">
                      <span className="font-medium">{c.name}</span>
                      {!c.can_write && (
                        <span className="text-xs opacity-70">{t("collab.viewing")}</span>
                      )}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {connectionStatus === "connected" && collaborators.length === 0 && (
              <p className="text-xs opacity-70">{t("collab.noCollaborators")}</p>
            )}
            {connectionStatus === "error" && (
              <p className="text-xs text-red-500">{t("collab.failedToConnect")}</p>
            )}
          </div>
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}

interface CollaboratorAvatarProps {
  collaborator: CollaboratorInfo;
  index: number;
}

function CollaboratorAvatar({ collaborator, index }: CollaboratorAvatarProps) {
  const { t } = useTranslation("documents");
  const initials = getInitials(collaborator.name);
  const avatarSrc =
    resolveUploadUrl(collaborator.avatar_url) || collaborator.avatar_base64 || undefined;

  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger asChild>
          <Avatar
            className={cn("h-7 w-7 border-2 border-white text-xs font-medium dark:border-gray-800")}
            style={{ zIndex: 10 - index }}
          >
            {avatarSrc ? <AvatarImage src={avatarSrc} alt={collaborator.name} /> : null}
            <AvatarFallback userId={collaborator.user_id}>{initials}</AvatarFallback>
          </Avatar>
        </TooltipTrigger>
        <TooltipContent className="bg-popover text-popover-foreground">
          <span>{collaborator.name}</span>
          {!collaborator.can_write && (
            <span className="ml-1 opacity-70">{t("collab.viewing")}</span>
          )}
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}

/**
 * Compact version for smaller spaces.
 */
export function CollaborationStatusCompact({
  connectionStatus,
  collaborators,
}: Pick<CollaborationStatusBadgeProps, "connectionStatus" | "collaborators">) {
  const { t } = useTranslation("documents");

  if (connectionStatus === "disconnected") {
    return null;
  }

  const isConnected = connectionStatus === "connected";

  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger asChild>
          <div className="flex items-center gap-1">
            <Circle
              className={cn(
                "h-2 w-2 fill-current",
                isConnected ? "text-green-500" : "text-yellow-500"
              )}
            />
            {collaborators.length > 0 && (
              <span className="text-muted-foreground text-xs">{collaborators.length}</span>
            )}
          </div>
        </TooltipTrigger>
        <TooltipContent className="bg-popover text-popover-foreground">
          {isConnected
            ? t("collab.collaborators", { count: collaborators.length })
            : t("collab.connecting")}
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}
