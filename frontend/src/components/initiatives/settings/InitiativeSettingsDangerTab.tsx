import { useTranslation } from "react-i18next";
import { Loader2, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { TabsContent } from "@/components/ui/tabs";

interface InitiativeSettingsDangerTabProps {
  isDefault: boolean;
  canDeleteInitiative: boolean;
  isDeleting: boolean;
  adminLabel: string;
  onDeleteInitiative: () => void;
}

export const InitiativeSettingsDangerTab = ({
  isDefault,
  canDeleteInitiative,
  isDeleting,
  adminLabel,
  onDeleteInitiative,
}: InitiativeSettingsDangerTabProps) => {
  const { t } = useTranslation(["initiatives", "common"]);

  return (
    <TabsContent value="danger">
      <Card className="border-destructive/40">
        <CardHeader>
          <CardTitle className="text-destructive">{t("settings.dangerTitle")}</CardTitle>
          <CardDescription>{t("settings.dangerDescription")}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {canDeleteInitiative ? (
            <Button
              type="button"
              variant="destructive"
              onClick={onDeleteInitiative}
              disabled={isDefault || isDeleting}
            >
              {isDeleting ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  {t("settings.deletingInitiative")}
                </>
              ) : (
                <>
                  <Trash2 className="mr-2 h-4 w-4" />
                  {t("settings.deleteInitiative")}
                </>
              )}
            </Button>
          ) : (
            <p className="text-muted-foreground text-sm">
              {t("settings.contactAdmin", { adminLabel })}
            </p>
          )}
          {isDefault ? (
            <p className="text-muted-foreground text-xs">{t("settings.defaultCannotDelete")}</p>
          ) : null}
        </CardContent>
      </Card>
    </TabsContent>
  );
};
