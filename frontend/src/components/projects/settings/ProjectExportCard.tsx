import { useState } from "react";
import { useTranslation } from "react-i18next";

import { exportProjectApiV1ProjectsProjectIdExportGet } from "@/api/generated/projects/projects";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { toast } from "@/lib/chesterToast";
import { downloadBlob } from "@/lib/csv";
import { getErrorMessage } from "@/lib/errorMessage";

interface ProjectExportCardProps {
  projectId: number;
  projectName: string;
  canWriteProject: boolean;
}

const safeFilename = (name: string): string =>
  name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 60) || "project";

export const ProjectExportCard = ({
  projectId,
  projectName,
  canWriteProject,
}: ProjectExportCardProps) => {
  const { t } = useTranslation("projects");
  const [isExporting, setIsExporting] = useState(false);

  const handleExport = async () => {
    setIsExporting(true);
    try {
      const envelope = await exportProjectApiV1ProjectsProjectIdExportGet(projectId);
      const blob = new Blob([JSON.stringify(envelope, null, 2)], {
        type: "application/json",
      });
      const date = new Date().toISOString().slice(0, 10);
      downloadBlob(blob, `${safeFilename(projectName)}-${date}.initiative-project.json`);
      toast.success(t("export.success"));
    } catch (err) {
      toast.error(getErrorMessage(err, "projects:export.error"));
    } finally {
      setIsExporting(false);
    }
  };

  return (
    <Card className="shadow-sm">
      <CardHeader>
        <CardTitle>{t("export.title")}</CardTitle>
        <CardDescription>{t("export.description")}</CardDescription>
      </CardHeader>
      <CardContent>
        <p className="text-muted-foreground text-sm">{t("export.detail")}</p>
      </CardContent>
      <CardFooter>
        {canWriteProject ? (
          <Button type="button" onClick={handleExport} disabled={isExporting}>
            {isExporting ? t("export.exporting") : t("export.exportButton")}
          </Button>
        ) : (
          <p className="text-muted-foreground text-sm">{t("export.noWriteAccess")}</p>
        )}
      </CardFooter>
    </Card>
  );
};
