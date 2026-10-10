/**
 * `/projects/$projectId/views` — the project's views and its task page,
 * edited in place.
 *
 * Who may is the server's answer on the set (the project's owner, the
 * initiative's managers, a community admin). The editor itself says when the
 * screen is too narrow to edit on, and keeps its draft while it is.
 */

import { useNavigate, useParams, useSearch } from "@tanstack/react-router";
import { useMemo } from "react";

import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { ToolSettingsPermissionRequired } from "@/components/tools/settings/ToolSettingsGuard";
import { taskPage } from "@/components/views/pages";
import { pageKey, ViewEditor } from "@/components/views/ViewEditor";
import { useProject, useProjectTaskStatuses } from "@/hooks/useProjects";
import { projectTarget, useProjectViews } from "@/hooks/useProjectViews";
import { useCommunityPath } from "@/lib/communityUrl";
import { toolSettingsRoute } from "@/lib/tools";

export const ProjectViewEditorPage = () => {
  const { projectId } = useParams({ strict: false }) as { projectId?: string };
  const { view, page } = useSearch({ strict: false }) as { view?: string; page?: "task" };
  const parsedId = projectId ? Number(projectId) : Number.NaN;
  const id = Number.isFinite(parsedId) ? parsedId : null;
  const navigate = useNavigate();
  const gp = useCommunityPath();

  const project = useProject(id).data;
  const statuses = useProjectTaskStatuses(id).data;
  const set = useProjectViews(id).data;
  const editing = useMemo(
    () =>
      project && statuses
        ? { id: project.id, initiativeId: project.initiative_id, statuses }
        : null,
    [project, statuses]
  );
  const pages = useMemo(() => (editing ? [taskPage(editing)] : []), [editing]);

  if (!project || !editing || !set || id === null) return null;
  if (!set.can_configure) return <ToolSettingsPermissionRequired />;
  return (
    <ViewEditor
      target={projectTarget(id)}
      initiativeId={project.initiative_id}
      project={editing}
      pages={pages}
      set={set}
      initialSlug={page === "task" ? pageKey("task") : view}
      onClose={() =>
        void navigate({
          to: gp(`${toolSettingsRoute(Tool.project, project.initiative_id, id)}/views`),
        })
      }
    />
  );
};
