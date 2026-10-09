import {
  type CollisionDetection,
  closestCorners,
  DndContext,
  type DndContextProps,
  type DragEndEvent,
  type DragOverEvent,
  DragOverlay,
  type DragStartEvent,
  type DroppableContainer,
  pointerWithin,
  type UniqueIdentifier,
} from "@dnd-kit/core";
import { useEffect, useMemo, useRef } from "react";
import { useTranslation } from "react-i18next";

import type {
  PropertyDefinitionRead,
  TaskListRead,
  TaskStatusRead,
} from "@/api/generated/initiativeAPI.schemas";
import { KanbanColumn } from "@/components/projects/KanbanColumn";
import { KanbanFieldsMenu } from "@/components/projects/KanbanFieldsMenu";
import { isKanbanFieldVisible, kanbanFieldsStorageKey } from "@/components/projects/kanbanFields";
import { priorityVariant } from "@/components/projects/projectTasksConfig";
import { TaskChecklistProgress } from "@/components/tasks/TaskChecklistProgress";
import { Badge } from "@/components/ui/badge";
import { MentionText } from "@/components/user/MentionText";
import { MentionedPeopleScope, ReportMentionedPeople } from "@/hooks/useMentionedPeople";
import { usePersistedColumnVisibility } from "@/hooks/usePersistedColumnVisibility";
import { useProperties } from "@/hooks/useProperties";
import { useCommunityPath } from "@/lib/communityUrl";
import { formatDateTime } from "@/lib/formatDate";
import { cn } from "@/lib/utils";
import type { ViewEnv } from "@/lib/views/fields";
import { taskFields } from "@/lib/views/tasks";
import type { ViewContext } from "@/lib/views/tree";
import type { TranslateFn } from "@/types/i18n";

import { TaskAssigneeList } from "./TaskAssigneeList";

type ProjectTasksKanbanViewProps = {
  projectId: number;
  initiativeId: number;
  taskStatuses: TaskStatusRead[];
  groupedTasks: Record<number, TaskListRead[]>;
  collapsedStatusIds: Set<number>;
  canReorderTasks: boolean;
  taskHref: (taskId: number) => string;
  sensors: DndContextProps["sensors"];
  activeTask: TaskListRead | null;
  onDragStart: (event: DragStartEvent) => void;
  onDragOver: (event: DragOverEvent) => void;
  onDragEnd: (event: DragEndEvent) => void;
  onDragCancel: () => void;
  onToggleCollapse: (statusId: number) => void;
  onArchiveDoneTasks?: (statusId: number) => void;
  isArchivingDoneTasks?: boolean;
  /** The properties the cards can show. When given, the board asks for none:
   *  a listing's preview has no initiative to ask. */
  propertyDefinitions?: PropertyDefinitionRead[];
};

// One empty list while the definitions load, so the fields aren't rebuilt on
// every pass until they arrive.
const NO_DEFINITIONS: PropertyDefinitionRead[] = [];

export const ProjectTasksKanbanView = ({
  projectId,
  initiativeId,
  taskStatuses,
  groupedTasks,
  collapsedStatusIds,
  canReorderTasks,
  taskHref,
  sensors,
  activeTask,
  onDragStart,
  onDragOver,
  onDragEnd,
  onDragCancel,
  onToggleCollapse,
  onArchiveDoneTasks,
  isArchivingDoneTasks,
  propertyDefinitions: givenDefinitions,
}: ProjectTasksKanbanViewProps) => {
  const scrollContainerRef = useRef<HTMLDivElement | null>(null);
  useHorizontalDragScroll(scrollContainerRef);

  // Which fields each card shows. Scoped to this project's initiative, like
  // the table's property columns, so the menu lists the properties a task
  // here can actually carry. No default-hidden ids: a board that has never
  // been configured shows everything, as it did before the menu existed.
  const { data: fetchedDefinitions = NO_DEFINITIONS } = useProperties({
    initiativeId,
    enabled: !givenDefinitions,
  });
  const propertyDefinitions = givenDefinitions ?? fetchedDefinitions;
  // The hook holds this in state, so its identity is stable between changes —
  // which is what lets the memoized card skip re-rendering on every parent pass.
  const [fieldVisibility, setFieldVisibility] = usePersistedColumnVisibility(
    kanbanFieldsStorageKey(projectId),
    EMPTY_DEFAULT_HIDDEN
  );
  // Built once per change rather than once per card, and stable in between so
  // the memoized cards skip re-rendering on an unrelated parent pass. What the
  // renderers share is held apart, so a change of fields redraws the cards but
  // not the values on them.
  const { t } = useTranslation(["projects", "dates", "relations"]);
  const communityPath = useCommunityPath();
  const env = useMemo<ViewEnv>(
    () => ({ t: t as TranslateFn, communityPath, taskHref }),
    [t, communityPath, taskHref]
  );
  const fields = useMemo(() => taskFields(propertyDefinitions), [propertyDefinitions]);
  const view = useMemo<ViewContext>(
    () => ({
      fields,
      variant: "card",
      isHidden: (fieldId) => !isKanbanFieldVisible(fieldVisibility, fieldId),
      env,
    }),
    [fields, fieldVisibility, env]
  );

  // The people the cards' excerpts mention, asked about once for the board.
  const excerpts = useMemo(
    () =>
      !view.isHidden("description")
        ? Object.values(groupedTasks).flatMap((tasks) =>
            tasks.flatMap((task) => task.description_excerpt ?? [])
          )
        : [],
    [groupedTasks, view]
  );

  const taskStatusesLength = taskStatuses.length;
  // Basis rather than min-width: it is what the collapse animates.
  const columnBasis = cn(
    "grow-0 basis-70 sm:grow",
    taskStatusesLength > 4 ? "sm:basis-80" : "sm:basis-89"
  );

  return (
    <MentionedPeopleScope>
      <ReportMentionedPeople texts={excerpts} />
      <DndContext
        sensors={sensors}
        collisionDetection={kanbanCollisionDetection}
        onDragStart={onDragStart}
        onDragOver={onDragOver}
        onDragEnd={onDragEnd}
        onDragCancel={onDragCancel}
      >
        <div className="mb-3 flex justify-end">
          <KanbanFieldsMenu
            fields={view.fields}
            visibility={fieldVisibility}
            onChange={setFieldVisibility}
          />
        </div>
        <div
          ref={scrollContainerRef}
          className="scrollbar-thin cursor-grab overflow-x-auto pb-4"
          data-kanban-scroll-container
        >
          <div className="flex gap-4">
            {taskStatuses.map((status) => {
              const isCollapsed = collapsedStatusIds.has(status.id);
              return (
                <KanbanColumn
                  key={status.id}
                  status={status}
                  tasks={groupedTasks[status.id] ?? []}
                  canWrite={canReorderTasks}
                  view={view}
                  collapsed={isCollapsed}
                  onToggleCollapse={onToggleCollapse}
                  taskCount={groupedTasks[status.id]?.length ?? 0}
                  className={cn(
                    "max-h-[70vh] min-h-[70vh] shrink-0 transition-[flex-basis,flex-grow] duration-200",
                    isCollapsed ? "grow-0 basis-12" : columnBasis
                  )}
                  onArchiveDoneTasks={onArchiveDoneTasks}
                  isArchiving={isArchivingDoneTasks}
                />
              );
            })}
          </div>
        </div>
        <DragOverlay>
          {activeTask ? <TaskDragOverlay task={activeTask} isHidden={view.isHidden} /> : null}
        </DragOverlay>
      </DndContext>
    </MentionedPeopleScope>
  );
};

// Prefer pointer-over targets to avoid snapping tasks into neighboring columns.
const kanbanCollisionDetection: CollisionDetection = (args) => {
  const pointerIntersections = pointerWithin(args);
  if (pointerIntersections.length > 0) {
    const prioritized = [...pointerIntersections].sort((a, b) => {
      const aType = getDroppableType(args.droppableContainers, a.id);
      const bType = getDroppableType(args.droppableContainers, b.id);

      if (aType === bType) {
        return 0;
      }
      if (aType === "task") {
        return -1;
      }
      if (bType === "task") {
        return 1;
      }
      return 0;
    });
    return prioritized;
  }
  return closestCorners(args);
};

const getDroppableType = (
  containers: DroppableContainer[],
  id: UniqueIdentifier
): string | undefined => containers.find((container) => container.id === id)?.data.current?.type;

const TaskDragOverlay = ({
  task,
  isHidden,
}: {
  task: TaskListRead;
  isHidden: ViewContext["isHidden"];
}) => {
  const { t } = useTranslation("projects");
  // The thing being dragged is the card, so it drops the same fields the card
  // dropped — otherwise picking one up puts back what you just turned off.
  const shows = (fieldId: string) => !isHidden(fieldId);
  return (
    <div className="w-64 space-y-3 rounded-lg border bg-card p-3 shadow-lg">
      <div className="space-y-1">
        <p className="font-medium">{task.title}</p>
        {shows("description") && task.description_excerpt ? (
          <p className="line-clamp-2 text-muted-foreground text-xs">
            <MentionText text={task.description_excerpt} disableLink />
          </p>
        ) : null}
      </div>
      <div className="space-y-1 text-muted-foreground text-xs">
        {shows("assignees") && task.assignees.length > 0 ? (
          <TaskAssigneeList assignees={task.assignees} className="text-xs" />
        ) : null}
        {shows("dueDate") && task.due_date ? (
          <p>{t("kanban.due", { date: formatDateTime(task.due_date) })}</p>
        ) : null}
      </div>
      {shows("checklist") ? <TaskChecklistProgress progress={task.checklist_progress} /> : null}
      {shows("priority") ? (
        <Badge variant={priorityVariant[task.priority]}>
          {t("kanban.priority", { priority: task.priority.replace("_", " ") })}
        </Badge>
      ) : null}
    </div>
  );
};

// Module-level so its identity is stable; the hook re-seeds defaults whenever
// this array's contents change.
const EMPTY_DEFAULT_HIDDEN: string[] = [];

const useHorizontalDragScroll = (ref: React.RefObject<HTMLDivElement | null>) => {
  useEffect(() => {
    const container = ref.current;
    if (!container) {
      return;
    }
    let isDragging = false;
    let startX = 0;
    let scrollStart = 0;
    let pointerId: number | null = null;

    const shouldIgnoreEvent = (target: EventTarget | null) => {
      if (!(target instanceof HTMLElement)) {
        return false;
      }
      return Boolean(target.closest('[data-kanban-scroll-lock="true"]'));
    };

    const handlePointerDown = (event: PointerEvent) => {
      if (event.button !== 0) {
        return;
      }
      if (shouldIgnoreEvent(event.target)) {
        return;
      }
      isDragging = true;
      pointerId = event.pointerId;
      startX = event.clientX;
      scrollStart = container.scrollLeft;
      container.setPointerCapture(event.pointerId);
      container.style.cursor = "grabbing";
      // Suppress the browser's native text-selection drag while we're
      // pan-scrolling, otherwise the user smears a selection across every
      // card their pointer moves over.
      container.style.userSelect = "none";
    };

    const handlePointerMove = (event: PointerEvent) => {
      if (!isDragging || pointerId !== event.pointerId) {
        return;
      }
      const delta = event.clientX - startX;
      container.scrollLeft = scrollStart - delta;
    };

    const stopDragging = () => {
      if (!isDragging) {
        return;
      }
      isDragging = false;
      if (pointerId !== null) {
        try {
          container.releasePointerCapture(pointerId);
        } catch {
          // ignore
        }
      }
      pointerId = null;
      container.style.cursor = "";
      container.style.userSelect = "";
    };

    container.addEventListener("pointerdown", handlePointerDown);
    container.addEventListener("pointermove", handlePointerMove);
    container.addEventListener("pointerup", stopDragging);
    container.addEventListener("pointerleave", stopDragging);
    container.addEventListener("pointercancel", stopDragging);

    return () => {
      container.removeEventListener("pointerdown", handlePointerDown);
      container.removeEventListener("pointermove", handlePointerMove);
      container.removeEventListener("pointerup", stopDragging);
      container.removeEventListener("pointerleave", stopDragging);
      container.removeEventListener("pointercancel", stopDragging);
    };
  }, [ref]);
};
