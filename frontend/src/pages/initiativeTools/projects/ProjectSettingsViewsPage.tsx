/**
 * `/settings/views` — the views this project offers, in order, and which one
 * it opens on.
 *
 * Configuring them is a step above write access (the project's owner, the
 * initiative's managers, or a community admin). The server decides, and says
 * so on the set. The tab bar offers this section only then, and the section
 * refuses anyone else on its own too, since the address is typeable.
 */

import { useParams } from "@tanstack/react-router";

import { ProjectViewsManager } from "@/components/projects/ProjectViewsManager";
import { ToolSettingsPermissionRequired } from "@/components/tools/settings/ToolSettingsGuard";
import { useProjectViews } from "@/hooks/useProjectViews";

export const ProjectSettingsViewsPage = () => {
  const { projectId } = useParams({ strict: false }) as { projectId?: string };
  const parsedId = projectId ? Number(projectId) : Number.NaN;
  const isValidId = Number.isFinite(parsedId);

  const set = useProjectViews(isValidId ? parsedId : null).data;

  if (!set) return null;
  if (!set.can_configure) return <ToolSettingsPermissionRequired />;

  return <ProjectViewsManager projectId={parsedId} set={set} />;
};
