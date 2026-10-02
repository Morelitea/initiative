import { FileDown } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { ExportWizard } from "@/components/exports/ExportWizard";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader } from "@/components/ui/card";

interface InitiativeSettingsExportTabProps {
  initiativeId: number;
}

export const InitiativeSettingsExportTab = ({ initiativeId }: InitiativeSettingsExportTabProps) => {
  const { t } = useTranslation("exports");
  const [wizardOpen, setWizardOpen] = useState(false);

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardDescription>{t("entry.initiativeDescription")}</CardDescription>
        </CardHeader>
        <CardContent>
          <Button onClick={() => setWizardOpen(true)}>
            <FileDown className="h-4 w-4" />
            {t("entry.open")}
          </Button>
        </CardContent>
      </Card>
      {/* Mounted outside the open check so a job started in the wizard keeps
          polling (and delivers its download) after the dialog closes. */}
      <ExportWizard
        scope={{ kind: "initiative", initiativeId }}
        open={wizardOpen}
        onOpenChange={setWizardOpen}
      />
    </div>
  );
};
