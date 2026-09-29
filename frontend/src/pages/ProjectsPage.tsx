import { useRouter, useSearch } from "@tanstack/react-router";
import { ArchiveRestore, CopyX, Plus } from "lucide-react";
import { useCallback, useEffect, useMemo } from "react";
import { useTranslation } from "react-i18next";

import type { ProjectRead } from "@/api/generated/initiativeAPI.schemas";
import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { invalidate, q } from "@/api/query-keys";
import { ToolImportAction, useToolImportAction } from "@/components/imports/ToolImportAction";
import { useRegisterPrimaryCreateAction } from "@/components/navigation/CreateActionContext";
import { PullToRefresh } from "@/components/PullToRefresh";
import { CreateProjectDialog } from "@/components/projects/CreateProjectDialog";
import { ProjectCardActionButton } from "@/components/projects/ProjectCardActionButton";
import { ProjectListPanel } from "@/components/projects/ProjectListPanel";
import {
  isProjectStatus,
  type ProjectStatus,
  ProjectStatusFilter,
} from "@/components/projects/ProjectStatusFilter";
import { Button } from "@/components/ui/button";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useAuth } from "@/hooks/useAuth";
import { useCreateFromSearchParam } from "@/hooks/useCreateFromSearchParam";
import { useToolCreateAccess } from "@/hooks/useInitiativeAccess";
import { useInitiatives } from "@/hooks/useInitiatives";
import {
  useProjectStatusCounts,
  useProjects,
  useRemoveProjectTemplate,
  useUnarchiveProject,
} from "@/hooks/useProjects";

/** Scoped to an initiative: the initiative page's Projects tab. */
type ProjectsViewProps = { fixedInitiativeId: number; canCreate?: boolean };

export const ProjectsView = ({ fixedInitiativeId, canCreate }: ProjectsViewProps) => {
  const { t } = useTranslation(["projects", "common", "access"]);
  const { user } = useAuth();
  // Single source of truth for "what can I do in each initiative" — honors
  // guild-admin / PAM / membership so this page never re-derives access from
  // raw membership flags (which would wrongly exclude guild admins).
  const lockedInitiativeId = typeof fixedInitiativeId === "number" ? fixedInitiativeId : null;

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
  const status: ProjectStatus = isProjectStatus(search.status) ? search.status : "active";
  const setStatus = useCallback(
    (next: ProjectStatus) => {
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
    ...(lockedInitiativeId ? { initiative_id: lockedInitiativeId } : {}),
    ...(status === "templates" ? { template: true } : {}),
    ...(status === "archived" ? { archived: true } : {}),
  };
  const projectsQuery = useProjects(
    Object.keys(projectsParams).length > 0 ? projectsParams : undefined
  );
  // Totals for all three states, so the filter can say how much sits behind
  // each one before it is opened.
  const statusCounts = useProjectStatusCounts(lockedInitiativeId);

  // This is a guild-scoped page and the initiatives list is cheap + cached, so
  // fetch it unconditionally. Create access is derived from the same payload
  // by useToolCreateAccess, which already honors guild-admin / PAM grants — no
  // need to pre-gate on a claimed manager role from user.initiative_roles (the
  // /users/me object no longer populates that field: initiative membership is
  // guild-schema content).
  const initiativesQuery = useInitiatives();
  // Canonical create answer: the locked/filtered initiative's server-computed
  // create flag, or (in the "All" view) whether any visible initiative grants
  // it. `creatableInitiatives` feeds the create dialog's initiative picker.
  const { canCreate: canCreateDerived, creatableInitiatives } = useToolCreateAccess(Tool.project, {
    initiativeId: lockedInitiativeId,
  });

  // Check if user can view projects for the filtered initiative
  // The cross-initiative tag browse has no one initiative to ask, and one not
  // loaded yet reads as yes; the server refuses what this would wrongly offer.
  const canViewProjects = useMemo(() => {
    const initiative = initiativesQuery.data?.find((i) => i.id === lockedInitiativeId);
    return initiative ? initiative.can.view.includes(Tool.project) : true;
  }, [lockedInitiativeId, initiativesQuery.data]);

  // An explicit canCreate prop (e.g. from InitiativeDetailPage) wins; otherwise
  // use the canonical derivation above.
  const canCreateProjects = canCreate ?? canCreateDerived;

  // Inside an initiative tab the import entry rides in the toolbar's shared
  // overflow menu; the unscoped page keeps its own kebab beside the heading.
  const projectImport = useToolImportAction({
    tool: Tool.project,
    canImport: canCreateProjects && lockedInitiativeId !== null,
    fixedInitiativeId: lockedInitiativeId ?? undefined,
  });

  // Drive the app-wide bottom-nav add button for this route.
  useRegisterPrimaryCreateAction(
    canCreateProjects ? { run: () => setIsComposerOpen(true), label: t("addProject") } : null
  );

  useEffect(() => {
    if (!canCreateProjects) {
      setIsComposerOpen(false);
    }
  }, [canCreateProjects, setIsComposerOpen]);

  const projects = useMemo(() => projectsQuery.data?.items ?? [], [projectsQuery.data]);

  const availableInitiatives = useMemo(() => {
    const initiatives = Array.isArray(initiativesQuery.data) ? initiativesQuery.data : [];
    return initiatives.sort((a, b) => a.name.localeCompare(b.name));
  }, [initiativesQuery.data]);

  // Filter initiatives where user can view projects (for the dropdown)
  const viewableInitiatives = useMemo(
    () => availableInitiatives.filter((initiative) => initiative.can.view.includes(Tool.project)),
    [availableInitiatives]
  );

  const lockedInitiativeName = lockedInitiativeId
    ? (availableInitiatives.find((init) => init.id === lockedInitiativeId)?.name ?? null)
    : null;

  // Get IDs of initiatives where user can view projects
  const viewableInitiativeIds = useMemo(() => {
    if (!user) return null;
    return new Set(viewableInitiatives.map((i) => i.id));
  }, [viewableInitiatives, user]);

  const accessRestricted = (
    <Card className="border-destructive/50 bg-destructive/5">
      <CardHeader>
        <CardTitle className="text-destructive">{t("accessRestricted")}</CardTitle>
        <CardDescription>{t("accessRestrictedDescription")}</CardDescription>
      </CardHeader>
    </Card>
  );

  const emptyStateCard = (title: string, description: string) => (
    <Card className="shadow-sm">
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
          canImport={canCreateProjects}
          fixedInitiativeId={lockedInitiativeId ?? undefined}
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
                label={t("archived.unarchive")}
                onClick={() => unarchiveProject.mutate(project.id)}
                disabled={unarchiveProject.isPending}
              />
            ) : null
        : undefined;

  return (
    <PullToRefresh onRefresh={handleRefresh}>
      <div className="space-y-6">
        {!lockedInitiativeId && (
          <div>
            <div className="flex items-baseline gap-4">
              <h1 className="font-semibold text-3xl tracking-tight">{t("title")}</h1>
              {canCreateProjects && (
                <Button size="sm" variant="outline" onClick={() => setIsComposerOpen(true)}>
                  <Plus className="h-4 w-4" />
                  {t("addProject")}
                </Button>
              )}
              <ToolImportAction tool={Tool.project} canImport={canCreateProjects} />
            </div>
            <p className="text-muted-foreground">{t("subtitle")}</p>
          </div>
        )}

        {!canViewProjects ? (
          accessRestricted
        ) : (
          <ProjectListPanel
            // Status is a different list, not a different filter of the same
            // one: remounting drops any in-flight bulk selection with it.
            key={status}
            projects={projects}
            isLoading={projectsQuery.isLoading}
            isError={projectsQuery.isError}
            loadingLabel={statusCopy.loading}
            errorLabel={statusCopy.error}
            noMatchesLabel={t("noMatchingProjects")}
            emptyState={emptyState}
            storagePrefix="project:list"
            // Inside an initiative every card would carry the same name.
            showInitiativeLabel={!lockedInitiativeId}
            sortable={status === "active"}
            viewableInitiativeIds={viewableInitiativeIds}
            renderItemActions={renderItemActions}
            toolbarActions={
              canCreateProjects && lockedInitiativeId ? (
                <Button
                  variant="outline"
                  size="sm"
                  className="h-9"
                  onClick={() => setIsComposerOpen(true)}
                >
                  <Plus className="h-4 w-4" />
                  {t("addProject")}
                </Button>
              ) : null
            }
            toolbarMenuItems={projectImport.menuItem}
            toolbarMenuDialogs={projectImport.dialog}
            leadingToolbar={
              <ProjectStatusFilter value={status} onChange={setStatus} counts={statusCounts} />
            }
          />
        )}

        {canCreateProjects && (
          <CreateProjectDialog
            open={isComposerOpen}
            onOpenChange={handleComposerOpenChange}
            lockedInitiativeId={lockedInitiativeId}
            lockedInitiativeName={lockedInitiativeName}
            creatableInitiatives={creatableInitiatives}
            initiativesQuery={{
              isLoading: initiativesQuery.isLoading,
              isError: initiativesQuery.isError,
            }}
            defaultInitiativeId={lockedInitiativeId ? String(lockedInitiativeId) : null}
            onCreated={() => handleComposerOpenChange(false)}
          />
        )}
      </div>
    </PullToRefresh>
  );
};
