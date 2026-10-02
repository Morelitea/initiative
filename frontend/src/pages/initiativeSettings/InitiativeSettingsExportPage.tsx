/**
 * `/settings/export` — take everything in this initiative away with you, and
 * whether anything in it may leave on its own.
 *
 * Managers and guild admins only, enforced here rather than by the tab bar
 * alone: the address is typeable, and an export is a bulk read of the whole
 * initiative.
 */

import { useTranslation } from "react-i18next";

import { InitiativeSettingsExportTab } from "@/components/initiatives/settings/InitiativeSettingsExportTab";
import { InitiativeSettingsPermissionRequired } from "@/components/initiatives/settings/InitiativeSettingsGuard";
import { useInitiativeSettings } from "@/hooks/useInitiativeSettings";
import { useUpdateInitiative } from "@/hooks/useInitiatives";
import { toast } from "@/lib/chesterToast";
import { getErrorMessage } from "@/lib/errorMessage";

export const InitiativeSettingsExportPage = () => {
  const { t } = useTranslation("initiatives");
  const { initiativeId, initiative, canManageMembers } = useInitiativeSettings();
  const updateInitiative = useUpdateInitiative({
    onSuccess: () => toast.success(t("settings.updated")),
    onError: (error) => toast.error(getErrorMessage(error, "initiatives:settings.updateError")),
  });

  if (!canManageMembers) {
    return <InitiativeSettingsPermissionRequired />;
  }

  return (
    <InitiativeSettingsExportTab
      initiativeId={initiativeId}
      keepContentIn={Boolean(initiative?.keep_content_in)}
      onChangeKeepContentIn={(next) =>
        updateInitiative.mutate({ initiativeId, data: { keep_content_in: next } })
      }
      isSaving={updateInitiative.isPending}
    />
  );
};
