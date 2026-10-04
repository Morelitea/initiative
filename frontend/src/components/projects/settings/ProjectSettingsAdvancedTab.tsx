import { Link } from "@tanstack/react-router";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { type ProjectRead, Tool } from "@/api/generated/initiativeAPI.schemas";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { useUpdateProject } from "@/hooks/useProjects";
import { useCommunityPath } from "@/lib/communityUrl";
import { toolListRoute } from "@/lib/tools";

interface ProjectSettingsAdvancedTabProps {
  project: ProjectRead;
  projectId: number;
  canWriteProject: boolean;
}

export const ProjectSettingsAdvancedTab = ({
  project,
  projectId,
  canWriteProject,
}: ProjectSettingsAdvancedTabProps) => {
  const { t } = useTranslation("projects");
  const gp = useCommunityPath();

  const [templateMessage, setTemplateMessage] = useState<string | null>(null);

  const toggleTemplateStatus = useUpdateProject(projectId, {
    onSuccess: (_data, vars) => {
      setTemplateMessage(
        vars.is_template
          ? t("settings.templateStatus.markedAsTemplate")
          : t("settings.templateStatus.removedFromTemplates")
      );
    },
  });

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("settings.templateStatus.title")}</CardTitle>
        <CardDescription>{t("settings.templateStatus.description")}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-2">
        <p className="text-muted-foreground text-sm">
          {project.is_template
            ? t("settings.templateStatus.isTemplate")
            : t("settings.templateStatus.isStandard")}
        </p>
        {templateMessage ? <p className="text-primary text-sm">{templateMessage}</p> : null}
      </CardContent>
      <CardFooter className="flex flex-wrap gap-3">
        {canWriteProject ? (
          <Button
            type="button"
            variant={project.is_template ? "outline" : "default"}
            onClick={() => {
              setTemplateMessage(null);
              toggleTemplateStatus.mutate({ is_template: !project.is_template });
            }}
            disabled={toggleTemplateStatus.isPending}
          >
            {project.is_template
              ? t("settings.templateStatus.convertToStandard")
              : t("settings.templateStatus.markAsTemplate")}
          </Button>
        ) : (
          <p className="text-muted-foreground text-sm">
            {t("settings.templateStatus.noWriteAccess")}
          </p>
        )}
        {project.is_template ? (
          <Button asChild variant="link" className="px-0">
            <Link to={gp(toolListRoute(Tool.project, project.initiative_id))}>
              {t("settings.templateStatus.viewAllTemplates")}
            </Link>
          </Button>
        ) : null}
      </CardFooter>
    </Card>
  );
};
