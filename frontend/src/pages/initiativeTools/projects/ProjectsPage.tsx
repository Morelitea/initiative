import { useRouter, useSearch } from "@tanstack/react-router";
import { ArchiveRestore, CopyX, Plus } from "lucide-react";
import { useCallback, useEffect } from "react";
import { useTranslation } from "react-i18next";

import type { ProjectRead } from "@/api/generated/initiativeAPI.schemas";
import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { invalidate, q } from "@/api/query-keys";
import { ToolImportAction, useToolImportAction } from "@/components/imports/ToolImportAction";
import { ToolViewFilter } from "@/components/initiativeTools/shared/ToolViewFilter";
import { useRegisterPrimaryCreateAction } from "@/components/navigation/CreateActionContext";
import { PullToRefresh } from "@/components/PullToRefresh";
import { CreateProjectDialog } from "@/components/projects/CreateProjectDialog";
import { ProjectCardActionButton } from "@/components/projects/ProjectCardActionButton";
import { ProjectListPanel } from "@/components/projects/ProjectListPanel";
import { Button } from "@/components/ui/button";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useCreateFromSearchParam } from "@/hooks/useCreateFromSearchParam";
import { useInitiative } from "@/hooks/useInitiatives";
import { useRemoveProjectTemplate, useUnarchiveProject } from "@/hooks/useProjects";
import { useToolCounts } from "@/hooks/useToolCounts";
import { isToolView, type ToolView, toolViewParams } from "@/lib/tools";

/** Scoped to an initiative: the initiative page's Projects tab. */
type ProjectsViewProps = { fixedInitiativeId: number; canCreate: boolean };

export const ProjectsView = ({ fixedInitiativeId, canCreate }: ProjectsViewProps) => {
  const { t } = useTranslation(["projects", "common"]);

  const handleRefresh = useCallback(async () => {
    await invalidate(q.allProjects());
  }, []);
  const {
    open: isComposerOpen,
    setOpen: setIsComposerOpen,
    onOpenChange: handleComposerOpenChange,
  } = useCreateFromSearchParam();

  const removeTemplate = useRemoveProjectTemplate();
  const unarchiveProject = useUnarchiveProject();

  // Which state of the list is shown. It lives in the URL so an archive view is
  // linkable and answers the back button.
  const router = useRouter();
  const search = useSearch({ strict: false }) as { status?: string };
  const status: ToolView = isToolView(search.status) ? search.status : "active";
  const setStatus = useCallback(
    (next: ToolView) => {
      void router.navigate({
        to: ".",
        search: { ...search, status: next === "active" ? undefined : next },
      });
    },
    [router, search]
  );

  // Scoped in SQL rather than filtered here: the list only ever shows one
  // initiative's projects, and the status picks
  // which of the three states the server returns.
  const projectsParams = {
    initiative_id: fixedInitiativeId,
    ...toolViewParams(Tool.project, status),
  };
  // How much sits behind each state, so the filter says so before it is
  // opened: scoped to the initiative, whatever the other filters say.
  const countsQuery = useToolCounts(Tool.project, { initiative_id: fixedInitiativeId });

  // The parent page's own cached read, for the create dialog's label.
  const initiativeName = useInitiative(fixedInitiativeId).data?.name ?? null;

  // The import entry rides in the toolbar's shared overflow menu.
  const projectImport = useToolImportAction({
    tool: Tool.project,
    canImport: canCreate,
    fixedInitiativeId,
  });

  // Drive the app-wide bottom-nav add button for this route.
  useRegisterPrimaryCreateAction(
    canCreate ? { run: () => setIsComposerOpen(true), label: t("addProject") } : null
  );

  useEffect(() => {
    if (!canCreate) {
      setIsComposerOpen(false);
    }
  }, [canCreate, setIsComposerOpen]);

  const emptyStateCard = (title: string, description: string) => (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
        <CardDescription>{description}</CardDescription>
      </CardHeader>
    </Card>
  );

  // One list, three states: the cards, filters, sorting, and bulk actions are
  // the same throughout — only the copy and the per-card action change.
  const statusCopy = {
    active: { loading: t("loading"), error: t("loadError") },
    templates: { loading: t("templates.loading"), error: t("templates.loadError") },
    archived: { loading: t("archived.loading"), error: t("archived.loadError") },
  }[status];

  const emptyState =
    status === "templates" ? (
      emptyStateCard(t("templates.noTemplates"), t("templates.noTemplatesDescription"))
    ) : status === "archived" ? (
      emptyStateCard(t("archived.noArchived"), t("archived.noArchivedDescription"))
    ) : (
      <div className="space-y-3">
        <p className="text-muted-foreground text-sm">{t("noProjects")}</p>
        <ToolImportAction
          tool={Tool.project}
          canImport={canCreate}
          fixedInitiativeId={fixedInitiativeId}
          variant="button"
        />
      </div>
    );

  const renderItemActions =
    status === "templates"
      ? (project: ProjectRead, { iconSize }: { iconSize: "sm" | "md" }) =>
          project.can.edit ? (
            <ProjectCardActionButton
              icon={CopyX}
              iconSize={iconSize}
              label={t("templates.stopUsingAsTemplate")}
              onClick={() => removeTemplate.mutate(project.id)}
              disabled={removeTemplate.isPending}
            />
          ) : null
      : status === "archived"
        ? // Nothing on an archived project may be edited; the way back out is
          // its own answer.
          (project: ProjectRead, { iconSize }: { iconSize: "sm" | "md" }) =>
            project.can.unarchive ? (
              <ProjectCardActionButton
                icon={ArchiveRestore}
                iconSize={iconSize}
                label={t("common:toolSettings.archive.unarchive")}
                onClick={() => unarchiveProject.mutate(project.id)}
                disabled={unarchiveProject.isPending}
              />
            ) : null
        : undefined;

  return (
    <PullToRefresh onRefresh={handleRefresh}>
      <div className="space-y-6">
        <ProjectListPanel
          // Status is a different list, not a different filter of the same
          // one: remounting drops any in-flight bulk selection with it.
          key={status}
          params={projectsParams}
          status={status}
          loadingLabel={statusCopy.loading}
          errorLabel={statusCopy.error}
          noMatchesLabel={t("noMatchingProjects")}
          emptyState={emptyState}
          storagePrefix="project:list"
          sortable={status === "active"}
          renderItemActions={renderItemActions}
          toolbarActions={
            canCreate ? (
              <Button size="sm" className="h-9" onClick={() => setIsComposerOpen(true)}>
                <Plus className="h-4 w-4" />
                {t("addProject")}
              </Button>
            ) : null
          }
          toolbarMenuItems={projectImport.menuItem}
          toolbarMenuDialogs={projectImport.dialog}
          leadingToolbar={
            <ToolViewFilter
              tool={Tool.project}
              value={status}
              onChange={setStatus}
              counts={countsQuery.data?.views}
            />
          }
        />

        {canCreate && (
          <CreateProjectDialog
            open={isComposerOpen}
            onOpenChange={handleComposerOpenChange}
            initiativeId={fixedInitiativeId}
            initiativeName={initiativeName}
            onCreated={() => handleComposerOpenChange(false)}
          />
        )}
      </div>
    </PullToRefresh>
  );
};
