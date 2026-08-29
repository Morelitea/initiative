/**
 * `/settings/export` — take everything in this initiative away with you.
 *
 * Managers and guild admins only, enforced here rather than by the tab bar
 * alone: the address is typeable, and an export is a bulk read of the whole
 * initiative.
 */

import { InitiativeSettingsExportTab } from "@/components/initiatives/settings/InitiativeSettingsExportTab";
import { InitiativeSettingsPermissionRequired } from "@/components/initiatives/settings/InitiativeSettingsGuard";
import { useInitiativeSettings } from "@/hooks/useInitiativeSettings";

export const InitiativeSettingsExportPage = () => {
  const { initiativeId, canManageMembers } = useInitiativeSettings();

  if (!canManageMembers) {
    return <InitiativeSettingsPermissionRequired />;
  }

  return <InitiativeSettingsExportTab initiativeId={initiativeId} />;
};
