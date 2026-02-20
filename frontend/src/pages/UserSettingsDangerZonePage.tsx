import { useState } from "react";
import { useRouter } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";
import { AlertTriangle, Unplug } from "lucide-react";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { DeleteAccountDialog } from "@/components/user/DeleteAccountDialog";
import { useServer } from "@/hooks/useServer";
import type { UserRead } from "@/api/generated/initiativeAPI.schemas";

interface UserSettingsDangerZonePageProps {
  user: UserRead;
  logout: () => void;
}

export const UserSettingsDangerZonePage = ({ user, logout }: UserSettingsDangerZonePageProps) => {
  const { t } = useTranslation("settings");
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const router = useRouter();
  const { isNativePlatform, getServerHostname, clearServerUrl } = useServer();

  const handleDeleteSuccess = () => {
    setDeleteDialogOpen(false);
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
        <>
          <div className="flex items-center gap-3">
            <div className="bg-muted rounded-lg p-2">
              <Unplug className="text-muted-foreground h-6 w-6" />
            </div>
            <div>
              <p className="text-lg font-semibold">{t("dangerZone.serverConnection")}</p>
              <p className="text-muted-foreground text-sm">
                {t("dangerZone.connectedTo", { hostname: getServerHostname() })}
              </p>
            </div>
          </div>

          <Card className="shadow-sm">
            <CardHeader>
              <CardTitle>{t("dangerZone.disconnectTitle")}</CardTitle>
              <CardDescription>{t("dangerZone.disconnectDescription")}</CardDescription>
            </CardHeader>
            <CardContent>
              <Button variant="outline" onClick={handleDisconnectServer}>
                {t("dangerZone.disconnectButton")}
              </Button>
            </CardContent>
          </Card>
        </>
      )}

      <div className="flex items-center gap-3">
        <div className="bg-destructive/10 rounded-lg p-2">
          <AlertTriangle className="text-destructive h-6 w-6" />
        </div>
        <div>
          <p className="text-lg font-semibold">{t("dangerZone.title")}</p>
          <p className="text-muted-foreground text-sm">{t("dangerZone.subtitle")}</p>
        </div>
      </div>

      <Card className="border-destructive/50 shadow-sm">
        <CardHeader>
          <CardTitle className="text-destructive">{t("dangerZone.deleteTitle")}</CardTitle>
          <CardDescription>{t("dangerZone.deleteDescription")}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="border-muted space-y-2 rounded-lg border p-4">
            <div className="flex items-center justify-between">
              <div className="flex-1">
                <h4 className="font-medium">{t("dangerZone.deactivateTitle")}</h4>
                <p className="text-muted-foreground mt-1 text-sm">
                  {t("dangerZone.deactivateDescription")}
                </p>
              </div>
            </div>
          </div>

          <div className="border-destructive/50 bg-destructive/5 space-y-2 rounded-lg border p-4">
            <div className="flex items-center justify-between">
              <div className="flex-1">
                <h4 className="text-destructive font-medium">
                  {t("dangerZone.permanentDeleteTitle")}
                </h4>
                <p className="text-muted-foreground mt-1 text-sm">
                  {t("dangerZone.permanentDeleteDescriptionText")}{" "}
                  <strong>{t("dangerZone.cannotBeUndone")}</strong>
                </p>
              </div>
            </div>
          </div>

          <div className="border-t pt-4">
            <Button variant="destructive" onClick={() => setDeleteDialogOpen(true)}>
              {t("dangerZone.deleteButton")}
            </Button>
          </div>
        </CardContent>
      </Card>

      <DeleteAccountDialog
        open={deleteDialogOpen}
        onOpenChange={setDeleteDialogOpen}
        onSuccess={handleDeleteSuccess}
        user={user}
      />
    </div>
  );
};
