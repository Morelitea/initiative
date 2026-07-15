import { FileDown } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { ExportWizard } from "@/components/exports/ExportWizard";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { TabsContent } from "@/components/ui/tabs";

interface InitiativeSettingsExportTabProps {
  initiativeId: number;
}

export const InitiativeSettingsExportTab = ({ initiativeId }: InitiativeSettingsExportTabProps) => {
  const { t } = useTranslation("exports");
  const [wizardOpen, setWizardOpen] = useState(false);

  return (
    <TabsContent value="export" className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle>{t("entry.initiativeTitle")}</CardTitle>
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
        scope="initiative"
        initiativeId={initiativeId}
        open={wizardOpen}
        onOpenChange={setWizardOpen}
      />
    </TabsContent>
  );
};
