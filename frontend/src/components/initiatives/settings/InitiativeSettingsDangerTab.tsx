import { Archive, ArchiveRestore, Loader2, Trash2 } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { TabsContent } from "@/components/ui/tabs";

interface InitiativeSettingsDangerTabProps {
  isDefault: boolean;
  isArchived: boolean;
  // Archiving (hide from the sidebar) is a guild-admin-only action.
  canArchiveInitiative: boolean;
  isArchiving: boolean;
  onToggleArchive: () => void;
  canDeleteInitiative: boolean;
  isDeleting: boolean;
  onDeleteInitiative: () => void;
}

export const InitiativeSettingsDangerTab = ({
  isDefault,
  isArchived,
  canArchiveInitiative,
  isArchiving,
  onToggleArchive,
  canDeleteInitiative,
  isDeleting,
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
          {canArchiveInitiative ? (
            <div className="space-y-2">
              <p className="text-muted-foreground text-sm">
                {isArchived ? t("settings.archivedDescription") : t("settings.archiveDescription")}
              </p>
              <Button
                type="button"
                variant="outline"
                onClick={onToggleArchive}
                disabled={isArchiving}
              >
                {isArchiving ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : isArchived ? (
                  <ArchiveRestore className="h-4 w-4" />
                ) : (
                  <Archive className="h-4 w-4" />
                )}
                {isArchived ? t("settings.unarchiveInitiative") : t("settings.archiveInitiative")}
              </Button>
            </div>
          ) : null}
          {canArchiveInitiative && canDeleteInitiative ? <div className="h-px bg-border" /> : null}
          {canDeleteInitiative ? (
            <Button
              type="button"
              variant="destructive"
              onClick={onDeleteInitiative}
              disabled={isDefault || isDeleting}
            >
              {isDeleting ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" />
                  {t("settings.deletingInitiative")}
                </>
              ) : (
                <>
                  <Trash2 className="h-4 w-4" />
                  {t("settings.deleteInitiative")}
                </>
              )}
            </Button>
          ) : (
            <p className="text-muted-foreground text-sm">{t("settings.contactAdmin")}</p>
          )}
          {isDefault ? (
            <p className="text-muted-foreground text-xs">{t("settings.defaultCannotDelete")}</p>
          ) : null}
        </CardContent>
      </Card>
    </TabsContent>
  );
};
