import { useTranslation } from "react-i18next";

import { ExportButton } from "@/components/exports/ExportButton";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

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
  const date = new Date().toISOString().slice(0, 10);

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
          // Engine-delivered: small projects download inline; large ones run
          // as a background job with the inbox-notification pickup.
          <ExportButton
            endpoint="/exports/project"
            params={{ project_id: projectId }}
            formats={[{ format: "json", labelKey: "export.formatJson" }]}
            filenameStem={`${safeFilename(projectName)}-${date}.initiative-project`}
            label={t("export.exportButton")}
            variant="default"
          />
        ) : (
          <p className="text-muted-foreground text-sm">{t("export.noWriteAccess")}</p>
        )}
      </CardFooter>
    </Card>
  );
};
