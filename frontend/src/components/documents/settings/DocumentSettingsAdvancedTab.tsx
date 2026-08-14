import { ArrowRightLeft, Copy } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

interface DocumentSettingsAdvancedTabProps {
  canManageDocument: boolean;
  onDuplicateClick: () => void;
  onCopyClick: () => void;
}

export const DocumentSettingsAdvancedTab = ({
  canManageDocument,
  onDuplicateClick,
  onCopyClick,
}: DocumentSettingsAdvancedTabProps) => {
  const { t } = useTranslation(["documents", "common"]);

  return (
    <>
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
            <Copy className="h-4 w-4" />
            {t("settings.duplicateDocument")}
          </Button>
          <Button
            type="button"
            variant="outline"
            onClick={onCopyClick}
            disabled={!canManageDocument}
          >
            <ArrowRightLeft className="h-4 w-4" />
            {t("settings.copyToInitiative")}
          </Button>
        </CardContent>
      </Card>
    </>
  );
};
