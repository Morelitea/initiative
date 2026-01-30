import { useState, type ReactNode } from "react";
import { useRouter } from "@tanstack/react-router";
import { Settings, Plus, Copy, LogOut, UserPlus, Users, FolderOpen } from "lucide-react";
import { toast } from "sonner";

import { apiClient } from "@/api/client";
import type { GuildInviteRead } from "@/types/api";

import {
  ContextMenu,
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuLabel,
  ContextMenuSeparator,
  ContextMenuTrigger,
} from "@/components/ui/context-menu";
import { LeaveGuildDialog } from "./LeaveGuildDialog";
import type { Guild } from "@/types/api";
import { useGuilds } from "@/hooks/useGuilds";

interface GuildContextMenuProps {
  guild: Guild;
  children: ReactNode;
}

export const GuildContextMenu = ({ guild, children }: GuildContextMenuProps) => {
  const router = useRouter();
  const { switchGuild, activeGuildId } = useGuilds();
  const [leaveDialogOpen, setLeaveDialogOpen] = useState(false);

  const isAdmin = guild.role === "admin";
  const [creatingInvite, setCreatingInvite] = useState(false);

  const handleInviteMembers = async () => {
    if (creatingInvite) return;
    setCreatingInvite(true);
    try {
      const response = await apiClient.post<GuildInviteRead>(`/guilds/${guild.id}/invites`, {});
      const inviteLink = `${window.location.origin}/invite/${response.data.code}`;
      await navigator.clipboard.writeText(inviteLink);
      toast.success("Invite link copied to clipboard");
    } catch (err) {
      console.error("Failed to create invite", err);
      toast.error("Failed to create invite");
    } finally {
      setCreatingInvite(false);
    }
  };

  const handleViewMembers = async () => {
    if (guild.id !== activeGuildId) {
      await switchGuild(guild.id);
    }
    router.navigate({ to: "/settings/guild/users" });
  };

  const handleViewInitiatives = async () => {
    if (guild.id !== activeGuildId) {
      await switchGuild(guild.id);
    }
    router.navigate({ to: "/initiatives" });
  };

  const handleGuildSettings = async () => {
    // Switch to this guild first if not active, then navigate to settings
    if (guild.id !== activeGuildId) {
      await switchGuild(guild.id);
    }
    router.navigate({ to: "/settings/guild" });
  };

  const handleCreateInitiative = async () => {
    // Switch to this guild first if not active, then navigate to initiatives with create param
    if (guild.id !== activeGuildId) {
      await switchGuild(guild.id);
    }
    router.navigate({ to: "/initiatives", search: { create: "true" } });
  };

  const handleCopyGuildId = () => {
    navigator.clipboard.writeText(String(guild.id));
    toast.success("Guild ID copied to clipboard");
  };

  return (
    <>
      <ContextMenu>
        <ContextMenuTrigger>{children}</ContextMenuTrigger>
        <ContextMenuContent className="w-48">
          <ContextMenuLabel className="truncate">{guild.name}</ContextMenuLabel>
          <ContextMenuSeparator />
          <ContextMenuItem onClick={handleViewInitiatives}>
            <FolderOpen className="mr-2 h-4 w-4" />
            View initiatives
          </ContextMenuItem>
          {isAdmin && (
            <>
              <ContextMenuItem onClick={handleViewMembers}>
                <Users className="mr-2 h-4 w-4" />
                View members
              </ContextMenuItem>
              <ContextMenuSeparator />
              <ContextMenuItem onClick={handleInviteMembers} disabled={creatingInvite}>
                <UserPlus className="mr-2 h-4 w-4" />
                {creatingInvite ? "Creating invite..." : "Invite members"}
              </ContextMenuItem>
              <ContextMenuItem onClick={handleCreateInitiative}>
                <Plus className="mr-2 h-4 w-4" />
                Create initiative
              </ContextMenuItem>
              <ContextMenuItem onClick={handleGuildSettings}>
                <Settings className="mr-2 h-4 w-4" />
                Guild settings
              </ContextMenuItem>
            </>
          )}
          <ContextMenuSeparator />
          <ContextMenuItem onClick={handleCopyGuildId}>
            <Copy className="mr-2 h-4 w-4" />
            Copy guild ID
          </ContextMenuItem>
          <ContextMenuSeparator />
          <ContextMenuItem
            onClick={() => setLeaveDialogOpen(true)}
            className="text-destructive focus:text-destructive"
          >
            <LogOut className="mr-2 h-4 w-4" />
            Leave guild
          </ContextMenuItem>
        </ContextMenuContent>
      </ContextMenu>
      <LeaveGuildDialog guild={guild} open={leaveDialogOpen} onOpenChange={setLeaveDialogOpen} />
    </>
  );
};
