import { useRouter } from "@tanstack/react-router";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { UserRead } from "@/api/generated/initiativeAPI.schemas";
import { SettingsSection } from "@/components/settings/SettingsSection";
import { Button } from "@/components/ui/button";
import { DeleteAccountDialog } from "@/components/user/DeleteAccountDialog";
import { useServer } from "@/hooks/useServer";

interface UserSettingsDangerZonePageProps {
  user: UserRead;
  logout: () => void;
}

/**
 * The three ways out: disconnect this device, stop using the account, end it.
 *
 * One section per way out, in increasing order of consequence, so the two that
 * cannot be confused with each other are not stacked inside a single card —
 * deactivating is reversible and deleting is not, and the sections say which is
 * which before the button does.
 */
export const UserSettingsDangerZonePage = ({ user, logout }: UserSettingsDangerZonePageProps) => {
  const { t } = useTranslation("settings");
  // ``null`` = closed; otherwise the selection the user clicked. Two
  // separate buttons (Deactivate / Delete) drive the same dialog with
  // a different ``initialAction`` so the choice is unambiguous and the
  // dialog skips its first step.
  const [pendingAction, setPendingAction] = useState<"deactivate" | "soft_delete" | null>(null);
  const router = useRouter();
  const { isNativePlatform, getServerHostname, clearServerUrl } = useServer();

  const handleDeleteSuccess = () => {
    setPendingAction(null);
    logout();
    router.navigate({ to: "/login" });
  };

  const handleDisconnectServer = async () => {
    await logout();
    clearServerUrl();
    router.navigate({ to: "/connect", replace: true });
  };

  return (
    <div className="space-y-6">
      {isNativePlatform && (
        <SettingsSection
          title={t("dangerZone.serverConnection")}
          description={t("dangerZone.connectedTo", { hostname: getServerHostname() })}
        >
          <p className="text-muted-foreground text-sm">{t("dangerZone.disconnectDescription")}</p>
          <Button variant="outline" onClick={handleDisconnectServer}>
            {t("dangerZone.disconnectButton")}
          </Button>
        </SettingsSection>
      )}

      <SettingsSection
        title={t("dangerZone.deactivateTitle")}
        description={t("dangerZone.deactivateDescription")}
      >
        <Button variant="outline" onClick={() => setPendingAction("deactivate")}>
          {t("dangerZone.deactivateButton")}
        </Button>
      </SettingsSection>

      <SettingsSection
        destructive
        title={t("dangerZone.permanentDeleteTitle")}
        description={
          <>
            {t("dangerZone.permanentDeleteDescriptionText")}{" "}
            <strong>{t("dangerZone.cannotBeUndone")}</strong>
          </>
        }
      >
        <Button variant="destructive" onClick={() => setPendingAction("soft_delete")}>
          {t("dangerZone.deleteButton")}
        </Button>
      </SettingsSection>

      <DeleteAccountDialog
        open={pendingAction !== null}
        onOpenChange={(open) => {
          if (!open) setPendingAction(null);
        }}
        onSuccess={handleDeleteSuccess}
        user={user}
        initialAction={pendingAction ?? undefined}
      />
    </div>
  );
};
