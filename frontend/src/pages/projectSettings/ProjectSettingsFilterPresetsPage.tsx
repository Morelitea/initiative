/**
 * `/settings/filter-presets` — the saved task filters this project offers, and
 * which one it opens on.
 *
 * Curating presets is a step above write access (a project manager, the owner,
 * or a guild admin). The server decides, and says so on the preset list.
 */

import { useParams } from "@tanstack/react-router";

import { ProjectFilterPresetsManager } from "@/components/projects/ProjectFilterPresetsManager";
import { useFilterPresets } from "@/hooks/useFilterPresets";
import { useProject } from "@/hooks/useProjects";

export const ProjectSettingsFilterPresetsPage = () => {
  const { projectId } = useParams({ strict: false }) as { projectId?: string };
  const parsedId = projectId ? Number(projectId) : Number.NaN;
  const isValidId = Number.isFinite(parsedId);

  const projectQuery = useProject(isValidId ? parsedId : null);
  const presetsQuery = useFilterPresets(isValidId ? parsedId : null);
  const project = projectQuery.data;

  if (!project) return null;

  return (
    <ProjectFilterPresetsManager
      project={project}
      canManage={presetsQuery.data?.can_manage ?? false}
    />
  );
};
