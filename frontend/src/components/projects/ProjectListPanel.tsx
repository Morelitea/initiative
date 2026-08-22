import {
  closestCenter,
  DndContext,
  type DragEndEvent,
  MouseSensor,
  TouchSensor,
  useSensor,
  useSensors,
} from "@dnd-kit/core";
import {
  arrayMove,
  SortableContext,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { FileDown, LayoutGrid, List, Pin as PinIcon } from "lucide-react";
import { type HTMLAttributes, type MouseEvent, type ReactNode, useState } from "react";
import { useTranslation } from "react-i18next";

import { type ProjectRead, Tool } from "@/api/generated/initiativeAPI.schemas";
import { invalidateAllProjects } from "@/api/query-keys";
import { BulkAccessBar, canManageSharing } from "@/components/access/BulkAccessBar";
import { BulkEditAccessDialog } from "@/components/access/BulkEditAccessDialog";
import { SelectableGridItem } from "@/components/access/SelectableGridItem";
import { BulkExportButton } from "@/components/exports/BulkExportButton";
import { ProjectCardLink, ProjectRowLink } from "@/components/projects/ProjectPreview";
import { ProjectsFilterBar } from "@/components/projects/ProjectsFilterBar";
import { Button } from "@/components/ui/button";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useGridSelection } from "@/hooks/useGridSelection";
import { useProjectListView } from "@/hooks/useProjectListView";
import { useReorderProjects } from "@/hooks/useProjects";

type ProjectListPanelProps = {
  /** The projects this tab lists — active, templates, or archived. */
  projects: ProjectRead[];
  isLoading: boolean;
  isError: boolean;
  loadingLabel: string;
  errorLabel: string;
  /** Rendered when the tab has no projects at all. */
  emptyState: ReactNode;
  /** Rendered when the filters exclude every project. */
  noMatchesLabel: string;
  /** View-preference namespace, e.g. `project:list` or `project:archive`. */
  storagePrefix: string;
  /** Drag-and-drop ordering plus a pinned section — the active list only. */
  sortable?: boolean;
  fixedTagIds?: number[];
  viewableInitiativeIds?: Set<number> | null;
  userId?: number;
  /** Buttons shown left of the grid/list toggle (create, import, …). */
  toolbarActions?: ReactNode;
  /** Leading control on the toolbar row — the status filter takes this slot,
   *  where the eye lands first rather than at the end of a row of buttons. */
  leadingToolbar?: ReactNode;
  /** Per-project control in the card's top-right cluster. Receives the icon
   *  size the current view mode uses so the control matches pin and favorite. */
  renderItemActions?: (project: ProjectRead, options: { iconSize: "sm" | "md" }) => ReactNode;
};

/**
 * One projects listing: toolbar, filters, and the cards themselves. Every tab
 * on the projects page renders through this so templates and archived projects
 * get the same cards, filters, sorting, and bulk actions the active list has.
 */
export const ProjectListPanel = ({
  projects,
  isLoading,
  isError,
  loadingLabel,
  errorLabel,
  emptyState,
  noMatchesLabel,
  storagePrefix,
  sortable = false,
  fixedTagIds,
  viewableInitiativeIds,
  userId,
  toolbarActions,
  leadingToolbar,
  renderItemActions,
}: ProjectListPanelProps) => {
  const { t } = useTranslation(["projects", "access"]);
  const view = useProjectListView({
    projects,
    storagePrefix,
    allowCustomSort: sortable,
    separatePinned: sortable,
    fixedTagIds,
    viewableInitiativeIds,
  });
  const { filteredProjects, pinnedProjects, sortedProjects, viewMode } = view;

  const selection = useGridSelection<ProjectRead>();
  const [bulkAccessOpen, setBulkAccessOpen] = useState(false);
  const reorderProjects = useReorderProjects();

  const sensors = useSensors(
    useSensor(MouseSensor, { activationConstraint: { distance: 5 } }),
    // Touch drags use a short press to keep scrolling intuitive.
    useSensor(TouchSensor, { activationConstraint: { delay: 200, tolerance: 8 } })
  );

  const handleProjectDragEnd = (event: DragEndEvent) => {
    const { active, over } = event;
    if (!over || active.id === over.id) {
      return;
    }
    view.setCustomOrder((prev) => {
      const oldIndex = prev.indexOf(Number(active.id));
      const newIndex = prev.indexOf(Number(over.id));
      if (oldIndex === -1 || newIndex === -1) {
        return prev;
      }
      const nextOrder = arrayMove(prev, oldIndex, newIndex);
      reorderProjects.mutate(nextOrder);
      return nextOrder;
    });
  };

  const itemActions = (project: ProjectRead) =>
    renderItemActions?.(project, { iconSize: viewMode === "list" ? "sm" : "md" });

  const renderProject = (project: ProjectRead, keyPrefix = "") => (
    <ProjectItem
      key={`${keyPrefix}${project.id}`}
      project={project}
      viewMode={viewMode}
      userId={userId}
      actions={itemActions(project)}
    />
  );

  const listClassName = viewMode === "list" ? "space-y-3" : "grid gap-4 md:grid-cols-2";
  const draggable = sortable && view.sortMode === "custom" && !selection.active;

  const projectItems = selection.active ? (
    <div className={listClassName}>
      {sortedProjects.map((project) => (
        <SelectableGridItem
          key={project.id}
          active
          selected={selection.selectedIds.has(project.id)}
          onToggle={() => selection.toggle(project)}
          label={project.name}
        >
          <ProjectItem project={project} viewMode={viewMode} userId={userId} />
        </SelectableGridItem>
      ))}
    </div>
  ) : draggable ? (
    <DndContext
      sensors={sensors}
      collisionDetection={closestCenter}
      onDragEnd={handleProjectDragEnd}
    >
      <SortableContext
        items={sortedProjects.map((project) => project.id.toString())}
        strategy={verticalListSortingStrategy}
      >
        <div className={listClassName}>
          {sortedProjects.map((project) => (
            <SortableProjectItem
              key={project.id}
              project={project}
              viewMode={viewMode}
              userId={userId}
              actions={itemActions(project)}
            />
          ))}
        </div>
      </SortableContext>
    </DndContext>
  ) : (
    <div className={listClassName}>{sortedProjects.map((project) => renderProject(project))}</div>
  );

  const pinnedSection =
    pinnedProjects.length > 0 ? (
      <div className="border-b pb-4">
        <div className="inline-flex items-center gap-2 font-medium text-muted-foreground text-sm">
          <PinIcon className="h-4 w-4" />
          {t("pinned")}
        </div>
        <div className={listClassName}>
          {pinnedProjects.map((project) => renderProject(project, "pinned-"))}
        </div>
      </div>
    ) : null;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        {leadingToolbar}
        <div className="ml-auto flex flex-wrap items-center gap-3">
          {toolbarActions}
          <Tabs
            value={viewMode}
            onValueChange={(value) => view.setViewMode(value as "grid" | "list")}
            className="w-auto"
          >
            <TabsList className="grid grid-cols-2">
              <TabsTrigger value="grid" className="inline-flex items-center gap-2">
                <LayoutGrid className="h-4 w-4" />
                {t("view.grid")}
              </TabsTrigger>
              <TabsTrigger value="list" className="inline-flex items-center gap-2">
                <List className="h-4 w-4" />
                {t("view.list")}
              </TabsTrigger>
            </TabsList>
          </Tabs>
          {sortedProjects.length > 0 && !selection.active && (
            <Button variant="outline" onClick={selection.enter}>
              {t("access:bulkBar.select")}
            </Button>
          )}
        </div>
      </div>

      <ProjectsFilterBar {...view.filterBarProps} />

      {isLoading ? (
        <p className="text-muted-foreground text-sm">{loadingLabel}</p>
      ) : isError ? (
        <p className="text-destructive text-sm">{errorLabel}</p>
      ) : projects.length === 0 ? (
        emptyState
      ) : filteredProjects.length === 0 ? (
        <p className="text-muted-foreground text-sm">{noMatchesLabel}</p>
      ) : (
        <>
          {selection.active ? (
            <BulkAccessBar
              count={selection.selectedItems.length}
              canManage={canManageSharing(selection.selectedItems)}
              onEditAccess={() => setBulkAccessOpen(true)}
              onExit={selection.exit}
            >
              {selection.selectedItems.length > 0 &&
                // Project backups require WRITE on every selected project
                // (the backend refuses mixed selections).
                (canManageSharing(selection.selectedItems) ? (
                  <BulkExportButton
                    tool={Tool.project}
                    ids={selection.selectedItems.map((p) => p.id)}
                  />
                ) : (
                  <Button variant="outline" size="sm" disabled title={t("export.noWriteAccess")}>
                    <FileDown className="h-4 w-4" />
                    <span className="hidden sm:ml-2 sm:inline">{t("export.exportButton")}</span>
                  </Button>
                ))}
            </BulkAccessBar>
          ) : (
            pinnedSection
          )}
          {sortedProjects.length > 0 ? (
            projectItems
          ) : pinnedProjects.length > 0 ? (
            <p className="text-muted-foreground text-sm">{t("onlyPinnedMatch")}</p>
          ) : null}
        </>
      )}

      <BulkEditAccessDialog
        open={bulkAccessOpen}
        onOpenChange={setBulkAccessOpen}
        items={selection.selectedItems}
        resourceType={Tool.project}
        invalidate={invalidateAllProjects}
        onSuccess={selection.exit}
      />
    </div>
  );
};

type ProjectItemProps = {
  project: ProjectRead;
  viewMode: "grid" | "list";
  userId?: number;
  actions?: ReactNode;
};

const ProjectItem = ({ project, viewMode, userId, actions }: ProjectItemProps) =>
  viewMode === "list" ? (
    <ProjectRowLink project={project} userId={userId} actions={actions} />
  ) : (
    <ProjectCardLink project={project} userId={userId} actions={actions} />
  );

const SortableProjectItem = ({ project, viewMode, userId, actions }: ProjectItemProps) => {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: project.id.toString(),
  });
  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
  };
  const dragHandleProps: HTMLAttributes<HTMLButtonElement> = {
    ...attributes,
    ...listeners,
    onClick: (event: MouseEvent<HTMLButtonElement>) => {
      event.preventDefault();
      event.stopPropagation();
    },
  };
  return (
    <div ref={setNodeRef} style={style} className={isDragging ? "opacity-70" : undefined}>
      {viewMode === "list" ? (
        <ProjectRowLink
          project={project}
          userId={userId}
          actions={actions}
          dragHandleProps={dragHandleProps}
        />
      ) : (
        <ProjectCardLink
          project={project}
          userId={userId}
          actions={actions}
          dragHandleProps={dragHandleProps}
        />
      )}
    </div>
  );
};
