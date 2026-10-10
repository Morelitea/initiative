/**
 * `/projects/$projectId/views` — the project's views, edited in place.
 *
 * Who may is the server's answer on the set (the project's owner, the
 * initiative's managers, a community admin). Editing needs room beside the
 * canvas, so a compact screen is told to come back on a wider one.
 */

import { useNavigate, useParams, useSearch } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";

import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { ToolSettingsPermissionRequired } from "@/components/tools/settings/ToolSettingsGuard";
import { ViewEditor } from "@/components/views/ViewEditor";
import { useProject, useProjectTaskStatuses } from "@/hooks/useProjects";
import { useProjectViews } from "@/hooks/useProjectViews";
import { atLeast, useWidthClass } from "@/hooks/useWidthClass";
import { useCommunityPath } from "@/lib/communityUrl";
import { toolSettingsRoute } from "@/lib/tools";

export const ProjectViewEditorPage = () => {
  const { t } = useTranslation("projects");
  const { projectId } = useParams({ strict: false }) as { projectId?: string };
  const { view } = useSearch({ strict: false }) as { view?: string };
  const parsedId = projectId ? Number(projectId) : Number.NaN;
  const id = Number.isFinite(parsedId) ? parsedId : null;
  const navigate = useNavigate();
  const gp = useCommunityPath();
  const wide = atLeast(useWidthClass(), "md");

  const project = useProject(id).data;
  const statuses = useProjectTaskStatuses(id).data;
  const set = useProjectViews(id).data;

  if (!project || !statuses || !set || id === null) return null;
  if (!set.can_configure) return <ToolSettingsPermissionRequired />;
  if (!wide) {
    return <p className="p-6 text-muted-foreground text-sm">{t("viewEditor.compact")}</p>;
  }

  return (
    <ViewEditor
      projectId={id}
      initiativeId={project.initiative_id}
      statuses={statuses}
      set={set}
      initialSlug={view}
      onClose={() =>
        void navigate({
          to: gp(`${toolSettingsRoute(Tool.project, project.initiative_id, id)}/views`),
        })
      }
    />
  );
};
