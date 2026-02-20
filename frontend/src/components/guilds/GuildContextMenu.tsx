import { useState, type ReactNode } from "react";
import { useRouter } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";
import { Settings, Plus, Copy, LogOut, UserPlus, Users, FolderOpen } from "lucide-react";
import { toast } from "sonner";

import { createGuildInviteApiV1GuildsGuildIdInvitesPost } from "@/api/generated/guilds/guilds";
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
  const { t } = useTranslation(["guilds", "nav"]);
  const { switchGuild, activeGuildId } = useGuilds();
  const [leaveDialogOpen, setLeaveDialogOpen] = useState(false);

  const isAdmin = guild.role === "admin";
  const [creatingInvite, setCreatingInvite] = useState(false);

  const handleInviteMembers = async () => {
    if (creatingInvite) return;
    setCreatingInvite(true);
    try {
      const data = (await createGuildInviteApiV1GuildsGuildIdInvitesPost(
        guild.id,
        {}
      )) as unknown as GuildInviteRead;
      const inviteLink = `${window.location.origin}/invite/${data.code}`;
      await navigator.clipboard.writeText(inviteLink);
      toast.success(t("inviteLinkCopied"));
    } catch (err) {
      console.error("Failed to create invite", err);
      toast.error(t("failedToCreateInvite"));
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
    toast.success(t("guildIdCopied"));
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
            {t("viewInitiatives")}
          </ContextMenuItem>
          {isAdmin && (
            <>
              <ContextMenuItem onClick={handleViewMembers}>
                <Users className="mr-2 h-4 w-4" />
                {t("viewMembers")}
              </ContextMenuItem>
              <ContextMenuSeparator />
              <ContextMenuItem onClick={handleInviteMembers} disabled={creatingInvite}>
                <UserPlus className="mr-2 h-4 w-4" />
                {creatingInvite ? t("creatingInvite") : t("inviteMembers")}
              </ContextMenuItem>
              <ContextMenuItem onClick={handleCreateInitiative}>
                <Plus className="mr-2 h-4 w-4" />
                {t("createInitiative")}
              </ContextMenuItem>
              <ContextMenuItem onClick={handleGuildSettings}>
                <Settings className="mr-2 h-4 w-4" />
                {t("nav:guildSettings")}
              </ContextMenuItem>
            </>
          )}
          <ContextMenuSeparator />
          <ContextMenuItem onClick={handleCopyGuildId}>
            <Copy className="mr-2 h-4 w-4" />
            {t("copyGuildId")}
          </ContextMenuItem>
          <ContextMenuSeparator />
          <ContextMenuItem
            onClick={() => setLeaveDialogOpen(true)}
            className="text-destructive focus:text-destructive"
          >
            <LogOut className="mr-2 h-4 w-4" />
            {t("leaveGuild")}
          </ContextMenuItem>
        </ContextMenuContent>
      </ContextMenu>
      <LeaveGuildDialog guild={guild} open={leaveDialogOpen} onOpenChange={setLeaveDialogOpen} />
    </>
  );
};
