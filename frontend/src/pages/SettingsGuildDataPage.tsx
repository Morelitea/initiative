import { FileDown, FileUp } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { ExportWizard } from "@/components/exports/ExportWizard";
import { DataJobsTable } from "@/components/imports/DataJobsTable";
import { ImportWizard } from "@/components/imports/ImportWizard";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

export const SettingsGuildDataPage = () => {
  const { t } = useTranslation(["exports", "imports"]);
  const [exportOpen, setExportOpen] = useState(false);
  const [importOpen, setImportOpen] = useState(false);

  // The whole guild settings section is admin-gated by GuildSettingsLayout,
  // and the backend re-checks guild adminship at request AND apply time.
  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>{t("exports:entry.guildTitle")}</CardTitle>
          <CardDescription>{t("exports:entry.guildDescription")}</CardDescription>
        </CardHeader>
        <CardContent>
          <Button onClick={() => setExportOpen(true)}>
            <FileDown className="h-4 w-4" />
            {t("exports:entry.open")}
          </Button>
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>{t("imports:dataTab.importTitle")}</CardTitle>
          <CardDescription>{t("imports:dataTab.importDescription")}</CardDescription>
        </CardHeader>
        <CardContent>
          <Button onClick={() => setImportOpen(true)}>
            <FileUp className="h-4 w-4" />
            {t("imports:dataTab.open")}
          </Button>
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>{t("exports:table.title")}</CardTitle>
          <CardDescription>{t("exports:table.description")}</CardDescription>
        </CardHeader>
        <CardContent>
          <DataJobsTable />
        </CardContent>
      </Card>
      {/* Mounted outside the open checks so jobs started in either wizard
          keep polling (and deliver their outcome) after the dialogs close. */}
      <ExportWizard scope="guild" open={exportOpen} onOpenChange={setExportOpen} />
      <ImportWizard open={importOpen} onOpenChange={setImportOpen} />
    </div>
  );
};

export default SettingsGuildDataPage;
