/**
 * `/settings/task-statuses` — the columns this project's tasks move through.
 */

import { useParams } from "@tanstack/react-router";

import { ProjectTaskStatusesManager } from "@/components/projects/ProjectTaskStatusesManager";
import { useProject } from "@/hooks/useProjects";
import { hasWriteAccess } from "@/lib/permissions";

export const ProjectSettingsTaskStatusesPage = () => {
  const { projectId } = useParams({ strict: false }) as { projectId?: string };
  const parsedId = projectId ? Number(projectId) : Number.NaN;
  const isValidId = Number.isFinite(parsedId);

  const projectQuery = useProject(isValidId ? parsedId : null);
  const project = projectQuery.data;

  if (!project) return null;

  return (
    <ProjectTaskStatusesManager
      projectId={project.id}
      canManage={hasWriteAccess(project.my_permission_level)}
    />
  );
};
