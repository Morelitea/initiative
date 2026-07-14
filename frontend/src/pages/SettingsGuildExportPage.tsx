import { FileDown } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { ExportJobsTable } from "@/components/exports/ExportJobsTable";
import { ExportWizard } from "@/components/exports/ExportWizard";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

export const SettingsGuildExportPage = () => {
  const { t } = useTranslation("exports");
  const [wizardOpen, setWizardOpen] = useState(false);

  // The whole guild settings section is admin-gated by GuildSettingsLayout,
  // and the backend re-checks guild adminship at request AND render time.
  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>{t("entry.guildTitle")}</CardTitle>
          <CardDescription>{t("entry.guildDescription")}</CardDescription>
        </CardHeader>
        <CardContent>
          <Button onClick={() => setWizardOpen(true)}>
            <FileDown className="h-4 w-4" />
            {t("entry.open")}
          </Button>
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>{t("table.title")}</CardTitle>
          <CardDescription>{t("table.description")}</CardDescription>
        </CardHeader>
        <CardContent>
          <ExportJobsTable />
        </CardContent>
      </Card>
      {/* Mounted outside the open check so a job started in the wizard keeps
          polling (and delivers its download) after the dialog closes. */}
      <ExportWizard scope="guild" open={wizardOpen} onOpenChange={setWizardOpen} />
    </div>
  );
};

export default SettingsGuildExportPage;
