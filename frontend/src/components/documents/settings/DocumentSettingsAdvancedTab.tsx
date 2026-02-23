import { useTranslation } from "react-i18next";
import { ArrowRightLeft, Copy, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { TabsContent } from "@/components/ui/tabs";

interface DocumentSettingsAdvancedTabProps {
  canManageDocument: boolean;
  isOwner: boolean;
  onDuplicateClick: () => void;
  onCopyClick: () => void;
  onDeleteClick: () => void;
}

export const DocumentSettingsAdvancedTab = ({
  canManageDocument,
  isOwner,
  onDuplicateClick,
  onCopyClick,
  onDeleteClick,
}: DocumentSettingsAdvancedTabProps) => {
  const { t } = useTranslation(["documents", "common"]);

  return (
    <TabsContent value="advanced" className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>{t("settings.copiesTitle")}</CardTitle>
          <CardDescription>{t("settings.copiesDescription")}</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-wrap gap-3">
          <Button
            type="button"
            variant="outline"
            onClick={onDuplicateClick}
            disabled={!canManageDocument}
          >
            <Copy className="mr-2 h-4 w-4" />
            {t("settings.duplicateDocument")}
          </Button>
          <Button
            type="button"
            variant="outline"
            onClick={onCopyClick}
            disabled={!canManageDocument}
          >
            <ArrowRightLeft className="mr-2 h-4 w-4" />
            {t("settings.copyToInitiative")}
          </Button>
        </CardContent>
      </Card>

      {isOwner ? (
        <Card className="border-destructive/40 bg-destructive/5 shadow-sm">
          <CardHeader>
            <CardTitle>{t("settings.dangerTitle")}</CardTitle>
            <CardDescription>{t("settings.dangerDescription")}</CardDescription>
          </CardHeader>
          <CardContent>
            <Button type="button" variant="destructive" onClick={onDeleteClick} disabled={!isOwner}>
              <Trash2 className="mr-2 h-4 w-4" />
              {t("settings.deleteDocument")}
            </Button>
          </CardContent>
        </Card>
      ) : null}
    </TabsContent>
  );
};
