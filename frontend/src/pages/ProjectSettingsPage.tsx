import { useParams } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";

import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { ProjectTaskStatusesManager } from "@/components/projects/ProjectTaskStatusesManager";
import { ProjectSettingsAdvancedTab } from "@/components/projects/settings/ProjectSettingsAdvancedTab";
import { ProjectSettingsDetailsTab } from "@/components/projects/settings/ProjectSettingsDetailsTab";
import { ToolSettingsPage } from "@/components/tools/settings/ToolSettingsPage";
import { useDeleteProject, useProject, useSetProjectGrants } from "@/hooks/useProjects";
import { hasWriteAccess } from "@/lib/permissions";

export const ProjectSettingsPage = () => {
  const { projectId } = useParams({ strict: false }) as { projectId?: string };
  const parsedId = projectId ? Number(projectId) : Number.NaN;
  const isValidId = Number.isFinite(parsedId);
  const { t } = useTranslation("projects");

  const projectQuery = useProject(isValidId ? parsedId : null);
  const setGrants = useSetProjectGrants(parsedId);
  const remove = useDeleteProject();

  const project = projectQuery.data;
  const canWrite = hasWriteAccess(project?.my_permission_level);

  return (
    <ToolSettingsPage
      tool={Tool.project}
      entity={project}
      isLoading={isValidId && projectQuery.isLoading}
      isError={!isValidId || projectQuery.isError}
      setGrants={setGrants}
      remove={remove}
      detailsExtra={
        project ? (
          <ProjectSettingsDetailsTab
            project={project}
            projectId={parsedId}
            canWriteProject={canWrite}
          />
        ) : null
      }
      extraTabs={
        project
          ? [
              {
                value: "task-statuses",
                label: t("settings.tabTaskStatuses"),
                content: <ProjectTaskStatusesManager projectId={project.id} canManage={canWrite} />,
              },
            ]
          : []
      }
      advancedExtra={
        project ? (
          <ProjectSettingsAdvancedTab
            project={project}
            projectId={parsedId}
            canWriteProject={canWrite}
          />
        ) : null
      }
    />
  );
};
