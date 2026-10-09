import { useParams, useRouter, useSearch } from "@tanstack/react-router";
import { useCallback, useEffect } from "react";
import { useTranslation } from "react-i18next";

import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { invalidate, q } from "@/api/query-keys";
import { ToolCommentsPanel } from "@/components/comments/ToolCommentsPanel";
import { PullToRefresh } from "@/components/PullToRefresh";
import { ProjectHeader } from "@/components/projects/ProjectHeader";
import { ProjectRelationships } from "@/components/projects/ProjectRelationships";
import { ProjectTasksSection } from "@/components/projects/ProjectTasksSection";
import { ProjectDetailSkeleton } from "@/components/skeletons/PageSkeletons";
import { ToolAccessStatus } from "@/components/ToolAccessStatus";
import { clearLastUsedProject } from "@/components/tasks/CreateTaskWizard";
import { useCanonicalInitiativeId } from "@/hooks/useCanonicalInitiativeId";
import { useToolCreateAccess } from "@/hooks/useInitiativeAccess";
import { useReadOnOpen } from "@/hooks/useNotifications";
import { useProject, useProjectTaskStatuses } from "@/hooks/useProjects";
import { useRecordRecentView } from "@/hooks/useRecents";
import { useCommunityPath } from "@/lib/communityUrl";
import { getHttpStatus } from "@/lib/errorMessage";
import { taskRoute, toolListRoute } from "@/lib/tools";

export const ProjectDetailPage = () => {
  const { t } = useTranslation("projects");
  const { communityId, projectId } = useParams({ strict: false }) as {
    communityId: string;
    projectId: string;
  };
  const router = useRouter();
  const gp = useCommunityPath();
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

  const recordViewMutation = useRecordRecentView(Tool.project, Number(communityId));
  const viewedProjectId = projectQuery.data?.id;
  useReadOnOpen(Tool.project, viewedProjectId);
  useEffect(() => {
    if (!viewedProjectId) {
      return;
    }
    recordViewMutation.mutate(viewedProjectId);
  }, [viewedProjectId, recordViewMutation.mutate]);

  const project = projectQuery.data;
  // Creating a file targets the project's initiative, so it follows that
  // initiative's server-computed create flag.
  const { canCreate: canCreateFiles } = useToolCreateAccess(Tool.file, {
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
      <div className="space-y-4">
        <ProjectHeader project={project} projectIsArchived={projectIsArchived} />
        <ProjectRelationships
          projectId={project.id}
          projectName={project.name}
          initiativeId={project.initiative_id}
          canCreate={Boolean(canCreateFiles && !projectIsArchived)}
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
          project={project}
        />
        <ToolCommentsPanel tool={Tool.project} entity={project} />
      </div>
    </PullToRefresh>
  );
};
