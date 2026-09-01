import { useParams } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";

import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { ProjectSettingsAdvancedTab } from "@/components/projects/settings/ProjectSettingsAdvancedTab";
import { ProjectSettingsDetailsTab } from "@/components/projects/settings/ProjectSettingsDetailsTab";
import { ToolSettingsLayout } from "@/components/tools/settings/ToolSettingsLayout";
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
    <ToolSettingsLayout
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
      // Two settings too large for a card. Each is served by its own route
      // beside the shared sections, so the value doubles as the URL segment.
      extraTabs={[
        { value: "filter-presets", label: t("settings.tabFilterPresets") },
        { value: "task-statuses", label: t("settings.tabTaskStatuses") },
      ]}
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
