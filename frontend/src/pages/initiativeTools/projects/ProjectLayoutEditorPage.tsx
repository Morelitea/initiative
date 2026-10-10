/**
 * `/projects/$projectId/layouts` — the project's layouts (its table, board and
 * calendar, and the task's detail), edited in place.
 *
 * Who may is the server's answer on the set (the project's owner, the
 * initiative's managers, a community admin). The editor itself says when the
 * screen is too narrow to edit on, and keeps its draft while it is.
 */

import { useNavigate, useParams, useSearch } from "@tanstack/react-router";
import { useMemo } from "react";

import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { LayoutEditor } from "@/components/layouts/LayoutEditor";
import { ToolSettingsPermissionRequired } from "@/components/tools/settings/ToolSettingsGuard";
import { useProject, useProjectTaskStatuses } from "@/hooks/useProjects";
import { useProjectLayouts } from "@/hooks/useToolLayouts";
import { useCommunityPath } from "@/lib/communityUrl";
import { toolSettingsRoute } from "@/lib/tools";

export const ProjectLayoutEditorPage = () => {
  const { projectId } = useParams({ strict: false }) as { projectId?: string };
  const { layout } = useSearch({ strict: false }) as { layout?: string };
  const parsedId = projectId ? Number(projectId) : Number.NaN;
  const id = Number.isFinite(parsedId) ? parsedId : null;
  const navigate = useNavigate();
  const gp = useCommunityPath();

  const project = useProject(id).data;
  const statuses = useProjectTaskStatuses(id).data;
  const set = useProjectLayouts(id).data;
  const editing = useMemo(
    () =>
      project && statuses
        ? { id: project.id, initiativeId: project.initiative_id, statuses }
        : null,
    [project, statuses]
  );

  if (!project || !editing || !set) return null;
  if (!set.can_configure) return <ToolSettingsPermissionRequired />;
  return (
    <LayoutEditor
      // Another project's editor starts afresh: a draft, and the question
      // before leaving it, belong to the project they were made for.
      key={project.id}
      project={editing}
      set={set}
      initialKind={layout}
      onClose={() =>
        void navigate({
          to: gp(`${toolSettingsRoute(Tool.project, project.initiative_id, project.id)}/layouts`),
        })
      }
    />
  );
};
