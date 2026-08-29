/**
 * `/settings/members` — the roster, and the requests waiting to join it.
 *
 * This is the address the directory's "waiting to join" badge links to, so a
 * manager who notices the count lands on the queue itself.
 */

import { useEffect, useState } from "react";

import type { InitiativeMemberRead } from "@/api/generated/initiativeAPI.schemas";
import { InitiativeSettingsPermissionRequired } from "@/components/initiatives/settings/InitiativeSettingsGuard";
import { InitiativeSettingsMembersTab } from "@/components/initiatives/settings/InitiativeSettingsMembersTab";
import { RemoveInitiativeMemberDialog } from "@/components/initiatives/settings/RemoveInitiativeMemberDialog";
import { useGuilds } from "@/hooks/useGuilds";
import { useInitiativeRoles } from "@/hooks/useInitiativeRoles";
import { useInitiativeSettings } from "@/hooks/useInitiativeSettings";

export const InitiativeSettingsMembersPage = () => {
  const { activeGuild } = useGuilds();
  const { initiativeId, initiative, canManageMembers } = useInitiativeSettings();
  const rolesQuery = useInitiativeRoles(initiativeId || null);

  const [selectedUserId, setSelectedUserId] = useState("");
  const [selectedRoleId, setSelectedRoleId] = useState("");
  const [memberToRemove, setMemberToRemove] = useState<InitiativeMemberRead | null>(null);

  // The role a new member gets unless the manager picks another.
  useEffect(() => {
    if (rolesQuery.data && !selectedRoleId) {
      const memberRole = rolesQuery.data.find((role) => role.name === "member");
      if (memberRole) {
        setSelectedRoleId(String(memberRole.id));
      }
    }
  }, [rolesQuery.data, selectedRoleId]);

  if (!canManageMembers) {
    return <InitiativeSettingsPermissionRequired />;
  }

  if (!initiative) {
    return null;
  }

  return (
    <>
      <InitiativeSettingsMembersTab
        initiativeId={initiativeId}
        members={initiative.members}
        roles={rolesQuery.data}
        canManageMembers={canManageMembers}
        activeGuildId={activeGuild?.id}
        selectedUserId={selectedUserId}
        setSelectedUserId={setSelectedUserId}
        selectedRoleId={selectedRoleId}
        setSelectedRoleId={setSelectedRoleId}
        onRemoveMember={setMemberToRemove}
      />
      <RemoveInitiativeMemberDialog
        initiativeId={initiativeId}
        member={memberToRemove}
        onOpenChange={setMemberToRemove}
      />
    </>
  );
};
