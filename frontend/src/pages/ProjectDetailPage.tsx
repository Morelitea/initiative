import { Link, useParams, useRouter, useSearch } from "@tanstack/react-router";
import { AlertCircle, SearchX, Settings, ShieldAlert } from "lucide-react";
import { useCallback, useEffect } from "react";
import { useTranslation } from "react-i18next";

import { Tool } from "@/api/generated/initiativeAPI.schemas";
import {
  invalidateAllTasks,
  invalidateProject,
  invalidateProjectTaskStatuses,
} from "@/api/query-keys";
import { PullToRefresh } from "@/components/PullToRefresh";
import { ProjectDocumentsSection } from "@/components/projects/ProjectDocumentsSection";
import { ProjectOverviewCard } from "@/components/projects/ProjectOverviewCard";
import { ProjectTasksSection } from "@/components/projects/ProjectTasksSection";
import { StatusMessage } from "@/components/StatusMessage";
import { clearLastUsedProject } from "@/components/tasks/CreateTaskWizard";
import { ToolBreadcrumb } from "@/components/tools/ToolBreadcrumb";
import { Button } from "@/components/ui/button";
import { useInitiativeAccess } from "@/hooks/useInitiativeAccess";
import { useProject, useProjectTaskStatuses } from "@/hooks/useProjects";
import { useRecordRecentView } from "@/hooks/useRecents";
import { getHttpStatus } from "@/lib/errorMessage";
import { useGuildPath } from "@/lib/guildUrl";
import { hasWriteAccess } from "@/lib/permissions";

export const ProjectDetailPage = () => {
  const { t } = useTranslation("projects");
  const { guildId, projectId } = useParams({ strict: false }) as {
    guildId: string;
    projectId: string;
  };
  const router = useRouter();
  const { permissionsFor } = useInitiativeAccess();
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
    await Promise.all([
      invalidateProject(parsedProjectId),
      invalidateAllTasks(),
      invalidateProjectTaskStatuses(parsedProjectId),
    ]);
  }, [parsedProjectId]);

  const projectQuery = useProject(Number.isFinite(parsedProjectId) ? parsedProjectId : null);

  // Tasks query is now inside ProjectTasksSection to support server-side filtering

  const taskStatusesQuery = useProjectTaskStatuses(
    Number.isFinite(parsedProjectId) ? parsedProjectId : null
  );

  const recordViewMutation = useRecordRecentView("project", Number(guildId));
  const viewedProjectId = projectQuery.data?.id;
  useEffect(() => {
    if (!viewedProjectId) {
      return;
    }
    recordViewMutation.mutate(viewedProjectId);
  }, [viewedProjectId, recordViewMutation.mutate]);

  const project = projectQuery.data;
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

  if (!Number.isFinite(parsedProjectId)) {
    return (
      <div className="space-y-4">
        <p className="text-destructive">{t("detail.invalidProjectId")}</p>
        <Button asChild variant="link" className="px-0">
          <Link to={gp("/projects")}>{t("detail.backToProjects")}</Link>
        </Button>
      </div>
    );
  }

  if (projectQuery.isLoading || taskStatusesQuery.isLoading) {
    return <p className="text-muted-foreground text-sm">{t("detail.loading")}</p>;
  }

  if (projectQuery.isError || taskStatusesQuery.isError || !project) {
    const status = getHttpStatus(projectQuery.error) ?? getHttpStatus(taskStatusesQuery.error);
    const backTo = gp("/projects");
    const backLabel = t("detail.backToProjects");

    if (status === 404 || status === 403) {
      clearLastUsedProject(parsedProjectId);
    }

    if (status === 404) {
      return (
        <StatusMessage
          icon={<SearchX />}
          title={t("detail.notFound")}
          description={t("detail.notFoundDescription")}
          backTo={backTo}
          backLabel={backLabel}
        />
      );
    }
    if (status === 403) {
      return (
        <StatusMessage
          icon={<ShieldAlert />}
          title={t("detail.noAccess")}
          description={t("detail.noAccessDescription")}
          backTo={backTo}
          backLabel={backLabel}
        />
      );
    }
    return (
      <StatusMessage
        icon={<AlertCircle />}
        title={t("detail.loadError")}
        backTo={backTo}
        backLabel={backLabel}
      />
    );
  }

  const myLevel = project?.my_permission_level;
  // Pure DAC: write access requires owner or write permission level
  const hasWritePermission = hasWriteAccess(myLevel);

  // Pure DAC: settings/write access based on permission level
  const canManageSettings = hasWritePermission;
  const canWriteProject = hasWritePermission;
  // Creating a document targets the project's initiative, so it follows that
  // initiative's server-computed create flag.
  const canCreateDocuments = project.initiative
    ? permissionsFor(project.initiative)[Tool.document].create
    : false;
  const canAttachDocuments = canWriteProject;
  // Pure DAC: any permission grants view access
  const canViewTaskDetails = Boolean(project && myLevel);
  const projectIsArchived = project.is_archived ?? false;
  const canEditTaskDetails = Boolean(project && canWriteProject && !projectIsArchived);

  const handleTaskClick = (taskId: number) => {
    if (!canViewTaskDetails) {
      return;
    }
    router.navigate({ to: gp(`/tasks/${taskId}`) });
  };

  return (
    <PullToRefresh onRefresh={handleRefresh}>
      <div className="space-y-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <ToolBreadcrumb
            tool={Tool.project}
            initiativeId={project.initiative_id}
            trail={[{ label: project.name }]}
          />
          {canManageSettings ? (
            <Button
              asChild
              variant="outline"
              size="sm"
              aria-label={t("detail.openProjectSettings")}
            >
              <Link to={gp(`/projects/${project.id}/settings`)}>
                <Settings className="h-5 w-5" /> {t("detail.projectSettings")}
              </Link>
            </Button>
          ) : null}
        </div>
        <ProjectOverviewCard project={project} projectIsArchived={projectIsArchived} />
        <ProjectDocumentsSection
          projectId={project.id}
          initiativeId={project.initiative_id}
          documents={project.documents ?? []}
          canCreate={Boolean(canCreateDocuments && !projectIsArchived)}
          canAttach={Boolean(canAttachDocuments && !projectIsArchived)}
        />
        <ProjectTasksSection
          projectId={project.id}
          initiativeId={project.initiative_id}
          taskStatuses={taskStatusesQuery.data ?? []}
          canEditTaskDetails={canEditTaskDetails}
          canWriteProject={Boolean(canWriteProject)}
          projectIsArchived={projectIsArchived}
          canViewTaskDetails={canViewTaskDetails}
          onTaskClick={handleTaskClick}
          initialComposerOpen={searchParams.create === "true"}
          onComposerOpenChange={handleComposerOpenChange}
        />
      </div>
    </PullToRefresh>
  );
};
