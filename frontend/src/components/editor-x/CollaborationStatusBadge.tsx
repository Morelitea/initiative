/**
 * Status badge component showing collaboration state and active collaborators.
 */

import { Circle, CloudOff, Users, Wifi, WifiOff } from "lucide-react";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import type { CollaboratorInfo } from "@/lib/yjs/CollaborationProvider";
import type { ConnectionStatus } from "@/hooks/useCollaboration";

export interface CollaborationStatusBadgeProps {
  connectionStatus: ConnectionStatus;
  collaborators: CollaboratorInfo[];
  isCollaborating: boolean;
  className?: string;
}

/**
 * Displays collaboration status and list of active collaborators.
 */
export function CollaborationStatusBadge({
  connectionStatus,
  collaborators,
  isCollaborating,
  className,
}: CollaborationStatusBadgeProps) {
  // Don't show anything if not enabled
  if (connectionStatus === "disconnected" && collaborators.length === 0) {
    return null;
  }

  const statusConfig = {
    connecting: {
      icon: Wifi,
      label: "Connecting...",
      color: "text-yellow-500",
      bgColor: "bg-yellow-100 dark:bg-yellow-900/20",
    },
    connected: {
      icon: Users,
      label: "Live editing",
      color: "text-green-500",
      bgColor: "bg-green-100 dark:bg-green-900/20",
    },
    disconnected: {
      icon: WifiOff,
      label: "Offline",
      color: "text-muted-foreground",
      bgColor: "bg-muted",
    },
    error: {
      icon: CloudOff,
      label: "Connection error",
      color: "text-red-500",
      bgColor: "bg-red-100 dark:bg-red-900/20",
    },
  };

  const config = statusConfig[connectionStatus];
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
              {isCollaborating && collaborators.length > 0 && (
                <span className="text-muted-foreground ml-0.5 text-xs">
                  ({collaborators.length})
                </span>
              )}
            </Badge>

            {/* Collaborator avatars */}
            {isCollaborating && collaborators.length > 0 && (
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
                <p className="text-xs opacity-70">Active collaborators:</p>
                <ul className="space-y-1">
                  {collaborators.map((c) => (
                    <li key={c.user_id} className="flex items-center gap-2 text-sm">
                      <span className="font-medium">{c.name}</span>
                      {!c.can_write && <span className="text-xs opacity-70">(viewing)</span>}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {connectionStatus === "connected" && collaborators.length === 0 && (
              <p className="text-xs opacity-70">
                No other collaborators. Changes sync in real-time when others join.
              </p>
            )}
            {connectionStatus === "error" && (
              <p className="text-xs text-red-500">
                Failed to connect. Changes will be saved locally.
              </p>
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

// Colors for collaborator avatars
const AVATAR_COLORS = [
  "bg-red-500",
  "bg-orange-500",
  "bg-amber-500",
  "bg-lime-500",
  "bg-emerald-500",
  "bg-cyan-500",
  "bg-blue-500",
  "bg-violet-500",
  "bg-pink-500",
];

function CollaboratorAvatar({ collaborator, index }: CollaboratorAvatarProps) {
  const colorClass = AVATAR_COLORS[collaborator.user_id % AVATAR_COLORS.length];
  const initials = collaborator.name
    .split(" ")
    .map((n) => n.charAt(0))
    .join("")
    .toUpperCase()
    .slice(0, 2);

  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger asChild>
          <div
            className={cn(
              "flex h-7 w-7 items-center justify-center rounded-full border-2 border-white text-xs font-medium text-white dark:border-gray-800",
              colorClass
            )}
            style={{ zIndex: 10 - index }}
          >
            {initials}
          </div>
        </TooltipTrigger>
        <TooltipContent className="bg-popover text-popover-foreground">
          <span>{collaborator.name}</span>
          {!collaborator.can_write && <span className="ml-1 opacity-70">(viewing)</span>}
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
            ? `${collaborators.length} collaborator${collaborators.length !== 1 ? "s" : ""}`
            : "Connecting..."}
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}
