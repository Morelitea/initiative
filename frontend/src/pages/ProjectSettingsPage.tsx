import { useParams, useSearch } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";

import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { ProjectFilterPresetsManager } from "@/components/projects/ProjectFilterPresetsManager";
import { ProjectTaskStatusesManager } from "@/components/projects/ProjectTaskStatusesManager";
import { ProjectSettingsAdvancedTab } from "@/components/projects/settings/ProjectSettingsAdvancedTab";
import { ProjectSettingsDetailsTab } from "@/components/projects/settings/ProjectSettingsDetailsTab";
import { ToolSettingsPage } from "@/components/tools/settings/ToolSettingsPage";
import { useFilterPresets } from "@/hooks/useFilterPresets";
import { useDeleteProject, useProject, useSetProjectGrants } from "@/hooks/useProjects";
import { hasWriteAccess } from "@/lib/permissions";

export const ProjectSettingsPage = () => {
  const { projectId } = useParams({ strict: false }) as { projectId?: string };
  const { tab } = useSearch({ strict: false }) as { tab?: string };
  const parsedId = projectId ? Number(projectId) : Number.NaN;
  const isValidId = Number.isFinite(parsedId);
  const { t } = useTranslation("projects");

  const projectQuery = useProject(isValidId ? parsedId : null);
  const setGrants = useSetProjectGrants(parsedId);
  const remove = useDeleteProject();

  const project = projectQuery.data;
  const canWrite = hasWriteAccess(project?.my_permission_level);
  // Curating presets and setting the default view is a step above write access
  // (a project manager, the owner, or a guild admin). The server decides, and
  // says so on the preset list.
  const presetsQuery = useFilterPresets(isValidId ? parsedId : null);
  const canManagePresets = presetsQuery.data?.can_manage ?? false;

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
      defaultTab={tab}
      extraTabs={
        project
          ? [
              {
                value: "filter-presets",
                label: t("settings.tabFilterPresets"),
                content: (
                  <ProjectFilterPresetsManager project={project} canManage={canManagePresets} />
                ),
              },
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
