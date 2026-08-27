import { useRouter } from "@tanstack/react-router";
import {
  Copy,
  FolderOpen,
  GripVertical,
  LogOut,
  Plus,
  Settings,
  UserPlus,
  Users,
} from "lucide-react";
import { type ReactNode, useState } from "react";
import { useTranslation } from "react-i18next";

import { createGuildInviteApiV1GuildsGuildIdInvitesPost } from "@/api/generated/guilds/guilds";
import type { GuildInviteRead, GuildRead } from "@/api/generated/initiativeAPI.schemas";
import {
  ContextMenu,
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuLabel,
  ContextMenuSeparator,
  ContextMenuTrigger,
} from "@/components/ui/context-menu";
import { useGuilds } from "@/hooks/useGuilds";
import { toast } from "@/lib/chesterToast";
import { getErrorMessage } from "@/lib/errorMessage";

import { LeaveGuildDialog } from "./LeaveGuildDialog";

interface GuildContextMenuProps {
  guild: GuildRead;
  children: ReactNode;
  /**
   * When provided, the menu offers a "Reorder guilds" action. Touch devices
   * have no drag affordance of their own (press-and-hold belongs to this
   * menu), so this is the way in to reorder mode there.
   */
  onReorder?: () => void;
}

export const GuildContextMenu = ({ guild, children, onReorder }: GuildContextMenuProps) => {
  const router = useRouter();
  const { t } = useTranslation(["guilds", "nav"]);
  const { switchGuild, activeGuildId } = useGuilds();
  const [leaveDialogOpen, setLeaveDialogOpen] = useState(false);

  const isAdmin = guild.role === "admin";
  const [creatingInvite, setCreatingInvite] = useState(false);
  // A guild at its operator-set seat cap mints no invite (the server refuses),
  // so the item says so rather than handing back an error toast. Both fields
  // are admin-only on the payload, and null max_users means uncapped.
  const atUserLimit = guild.max_users != null && guild.member_count >= guild.max_users;

  const handleInviteMembers = async () => {
    if (creatingInvite || atUserLimit) return;
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
      toast.error(getErrorMessage(err, "guilds:failedToCreateInvite"));
    } finally {
      setCreatingInvite(false);
    }
  };

  const handleViewMembers = async () => {
    if (guild.id !== activeGuildId) {
      await switchGuild(guild.id);
    }
    router.navigate({ to: "/g/$guildId/settings/users", params: { guildId: String(guild.id) } });
  };

  const handleViewInitiatives = async () => {
    if (guild.id !== activeGuildId) {
      await switchGuild(guild.id);
    }
    router.navigate({ to: "/g/$guildId/i", params: { guildId: String(guild.id) } });
  };

  const handleGuildSettings = async () => {
    // Switch to this guild first if not active, then navigate to settings
    if (guild.id !== activeGuildId) {
      await switchGuild(guild.id);
    }
    router.navigate({ to: "/g/$guildId/settings", params: { guildId: String(guild.id) } });
  };

  const handleCreateInitiative = async () => {
    // Switch to this guild first if not active, then navigate to initiatives with create param
    if (guild.id !== activeGuildId) {
      await switchGuild(guild.id);
    }
    router.navigate({
      to: "/g/$guildId/i",
      params: { guildId: String(guild.id) },
      search: { create: "true" },
    });
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
              <ContextMenuItem
                onClick={handleInviteMembers}
                disabled={creatingInvite || atUserLimit}
              >
                <UserPlus className="mr-2 h-4 w-4" />
                {creatingInvite
                  ? t("creatingInvite")
                  : atUserLimit
                    ? t("inviteMembersGuildFull")
                    : t("inviteMembers")}
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
          {onReorder ? (
            <ContextMenuItem onClick={onReorder}>
              <GripVertical className="mr-2 h-4 w-4" />
              {t("reorderGuilds")}
            </ContextMenuItem>
          ) : null}
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
