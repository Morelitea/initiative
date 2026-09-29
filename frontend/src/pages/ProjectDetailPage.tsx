import { Link, useParams, useRouter, useSearch } from "@tanstack/react-router";
import { Settings } from "lucide-react";
import { useCallback, useEffect } from "react";
import { useTranslation } from "react-i18next";

import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { invalidate, q } from "@/api/query-keys";
import { ToolCommentsPanel } from "@/components/comments/ToolCommentsPanel";
import { PullToRefresh } from "@/components/PullToRefresh";
import { ProjectDocumentsSection } from "@/components/projects/ProjectDocumentsSection";
import { ProjectOverviewCard } from "@/components/projects/ProjectOverviewCard";
import { ProjectTasksSection } from "@/components/projects/ProjectTasksSection";
import { ProjectDetailSkeleton } from "@/components/skeletons/PageSkeletons";
import { ToolAccessStatus } from "@/components/ToolAccessStatus";
import { clearLastUsedProject } from "@/components/tasks/CreateTaskWizard";
import { ToolBreadcrumb } from "@/components/tools/ToolBreadcrumb";
import { Button } from "@/components/ui/button";
import { useCanonicalInitiativeId } from "@/hooks/useCanonicalInitiativeId";
import { useToolCreateAccess } from "@/hooks/useInitiativeAccess";
import { useReadOnOpen } from "@/hooks/useNotifications";
import { useProject, useProjectTaskStatuses } from "@/hooks/useProjects";
import { useRecordRecentView } from "@/hooks/useRecents";
import { getHttpStatus } from "@/lib/errorMessage";
import { useGuildPath } from "@/lib/guildUrl";
import { taskRoute, toolListRoute, toolSettingsRoute } from "@/lib/tools";

export const ProjectDetailPage = () => {
  const { t } = useTranslation("projects");
  const { guildId, projectId } = useParams({ strict: false }) as {
    guildId: string;
    projectId: string;
  };
  const router = useRouter();
  const gp = useGuildPath();
  const searchParams = useSearch({ strict: false }) as { create?: string };
  const parsedProjectId = Number(projectId);

  // Clear ?create from URL when the task composer closes
  const handleComposerOpenChange = useCallback(
    (isOpen: boolean) => {
      if (!isOpen && searchParams.create) {
        void router.navigate({
          to: ".",
          search: {},
          replace: true,
        });
      }
    },
    [searchParams.create, router]
  );

  const handleRefresh = useCallback(async () => {
    await invalidate(
      q.project(parsedProjectId),
      q.allTasks(),
      q.projectTaskStatuses(parsedProjectId)
    );
  }, [parsedProjectId]);

  const projectQuery = useProject(Number.isFinite(parsedProjectId) ? parsedProjectId : null);

  // Tasks query is now inside ProjectTasksSection to support server-side filtering

  const taskStatusesQuery = useProjectTaskStatuses(
    Number.isFinite(parsedProjectId) ? parsedProjectId : null
  );

  const recordViewMutation = useRecordRecentView("project", Number(guildId));
  const viewedProjectId = projectQuery.data?.id;
  useReadOnOpen(Tool.project, viewedProjectId);
  useEffect(() => {
    if (!viewedProjectId) {
      return;
    }
    recordViewMutation.mutate(viewedProjectId);
  }, [viewedProjectId, recordViewMutation.mutate]);

  const project = projectQuery.data;
  // Creating a document targets the project's initiative, so it follows that
  // initiative's server-computed create flag.
  const { canCreate: canCreateDocuments } = useToolCreateAccess(Tool.document, {
    initiativeId: project?.initiative_id,
  });
  // The path supplies the initiative while this loads, but the entity is the
  // authority once it arrives — a URL naming a different one is corrected
  // rather than left to build links into an initiative it isn't in.
  const initiativeId = useCanonicalInitiativeId(project?.initiative_id);
  const projectName = project?.name;
  useEffect(() => {
    if (typeof document === "undefined" || !projectName) {
      return;
    }
    const previousTitle = document.title || "Initiative";
    document.title = `${projectName} - Initiative`;
    return () => {
      document.title = previousTitle;
    };
  }, [projectName]);

  // Stable identity: the task table's column definitions and its memoized
  // cells both key off this. Declared with the other hooks, above the early
  // returns below.
  const taskHref = useCallback(
    (taskId: number) => gp(taskRoute(initiativeId, parsedProjectId, taskId)),
    [gp, initiativeId, parsedProjectId]
  );

  if (projectQuery.isLoading || taskStatusesQuery.isLoading) {
    return <ProjectDetailSkeleton label={t("detail.loading")} />;
  }

  if (projectQuery.isError || taskStatusesQuery.isError || !project) {
    const error = projectQuery.error ?? taskStatusesQuery.error;
    const status = getHttpStatus(error);
    if (status === 404 || status === 403) {
      clearLastUsedProject(parsedProjectId);
    }
    return (
      <ToolAccessStatus
        error={error}
        keys="projects:detail."
        backTo={gp(toolListRoute(Tool.project, initiativeId))}
        backLabel={t("detail.backToProjects")}
      />
    );
  }

  const canEdit = project.can.edit;
  const projectIsArchived = project.archived_at !== null;

  return (
    <PullToRefresh onRefresh={handleRefresh}>
      <div className="space-y-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <ToolBreadcrumb
            tool={Tool.project}
            initiativeId={project.initiative_id}
            trail={[{ label: project.name }]}
          />
          {canEdit ? (
            <Button
              asChild
              variant="outline"
              size="sm"
              aria-label={t("detail.openProjectSettings")}
            >
              <Link to={gp(toolSettingsRoute(Tool.project, initiativeId, project.id))}>
                <Settings className="h-5 w-5" /> {t("detail.projectSettings")}
              </Link>
            </Button>
          ) : null}
        </div>
        <ProjectOverviewCard project={project} projectIsArchived={projectIsArchived} />
        <ProjectDocumentsSection
          projectId={project.id}
          projectName={project.name}
          initiativeId={project.initiative_id}
          canCreate={Boolean(canCreateDocuments && !projectIsArchived)}
          canAttach={canEdit}
        />
        <ProjectTasksSection
          projectId={project.id}
          initiativeId={project.initiative_id}
          taskStatuses={taskStatusesQuery.data ?? []}
          projectDefaultViewMode={project.default_view_mode}
          canEditTaskDetails={canEdit}
          projectIsArchived={projectIsArchived}
          taskHref={taskHref}
          initialComposerOpen={searchParams.create === "true"}
          onComposerOpenChange={handleComposerOpenChange}
        />
        <ToolCommentsPanel tool={Tool.project} entity={project} canModerate={canEdit} />
      </div>
    </PullToRefresh>
  );
};
