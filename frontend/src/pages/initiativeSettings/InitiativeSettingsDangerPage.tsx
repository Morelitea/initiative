/**
 * `/settings/danger` — archiving the initiative, and deleting it.
 *
 * Both actions are the guild admin's: the section itself is readable by anyone
 * who may configure the initiative (it explains what archiving and deletion
 * mean, and who to ask), while each control stays gated on the standing it
 * actually needs.
 */

import { useRouter } from "@tanstack/react-router";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { DeleteInitiativeDialog } from "@/components/initiatives/DeleteInitiativeDialog";
import { InitiativeSettingsDangerTab } from "@/components/initiatives/settings/InitiativeSettingsDangerTab";
import { InitiativeSettingsPermissionRequired } from "@/components/initiatives/settings/InitiativeSettingsGuard";
import { useInitiativeSettings } from "@/hooks/useInitiativeSettings";
import { useDeleteInitiative, useUpdateInitiative } from "@/hooks/useInitiatives";
import { toast } from "@/lib/chesterToast";
import { getErrorMessage } from "@/lib/errorMessage";
import { useGuildPath } from "@/lib/guildUrl";

export const InitiativeSettingsDangerPage = () => {
  const { t } = useTranslation(["initiatives", "common"]);
  const gp = useGuildPath();
  const router = useRouter();
  const { initiativeId, initiative, canManageMembers, canDeleteInitiative, isGuildAdmin } =
    useInitiativeSettings();

  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);

  const updateInitiative = useUpdateInitiative({
    onSuccess: () => {
      toast.success(t("settings.updated"));
    },
    onError: (error) => {
      toast.error(getErrorMessage(error, "initiatives:settings.updateError"));
    },
  });

  const deleteInitiative = useDeleteInitiative({
    onSuccess: () => {
      toast.success(t("settings.deleted"));
      router.navigate({ to: gp("/") });
    },
    onError: (error) => {
      toast.error(getErrorMessage(error, "initiatives:settings.deleteError"));
    },
  });

  if (!canManageMembers && !canDeleteInitiative) {
    return <InitiativeSettingsPermissionRequired />;
  }

  if (!initiative) {
    return null;
  }

  return (
    <>
      <InitiativeSettingsDangerTab
        isDefault={initiative.is_default}
        isArchived={initiative.is_archived}
        canArchiveInitiative={isGuildAdmin}
        isArchiving={updateInitiative.isPending}
        onToggleArchive={() =>
          updateInitiative.mutate({
            initiativeId,
            data: { is_archived: !initiative.is_archived },
          })
        }
        canDeleteInitiative={canDeleteInitiative}
        isDeleting={deleteInitiative.isPending}
        onDeleteInitiative={() => {
          // The default initiative is the guild's floor and cannot be deleted;
          // the section says so rather than opening a dialog that would fail.
          if (initiative.is_default) {
            return;
          }
          setShowDeleteConfirm(true);
        }}
      />
      {/* Shared with the guild settings Initiatives table, so there is a single
          delete workflow. */}
      <DeleteInitiativeDialog
        open={showDeleteConfirm}
        onOpenChange={setShowDeleteConfirm}
        initiativeName={initiative.name}
        isDeleting={deleteInitiative.isPending}
        onConfirm={() => {
          deleteInitiative.mutate(initiativeId);
          setShowDeleteConfirm(false);
        }}
      />
    </>
  );
};
