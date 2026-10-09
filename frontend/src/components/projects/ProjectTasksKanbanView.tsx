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
import { KanbanColumn, TaskCard } from "@/components/projects/KanbanColumn";
import { KanbanFieldsMenu } from "@/components/projects/KanbanFieldsMenu";
import { buildKanbanCardFields, kanbanFieldsStorageKey } from "@/components/projects/kanbanFields";
import type { TaskCardContext } from "@/components/tasks/parts";
import { MentionedPeopleScope, ReportMentionedPeople } from "@/hooks/useMentionedPeople";
import { usePersistedColumnVisibility } from "@/hooks/usePersistedColumnVisibility";
import { useProperties } from "@/hooks/useProperties";
import { type ListedProject, useTaskBlocks } from "@/hooks/useTaskBlocks";
import { cn } from "@/lib/utils";
import type { TranslateFn } from "@/types/i18n";

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
  /** The project, for the plug-in blocks confined to the listing it was installed from. */
  project?: ListedProject | null;
};

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
  project,
}: ProjectTasksKanbanViewProps) => {
  const scrollContainerRef = useRef<HTMLDivElement | null>(null);
  useHorizontalDragScroll(scrollContainerRef);

  // Which fields each card shows. Scoped to this project's initiative, like
  // the table's property columns, so the menu lists the properties a task
  // here can actually carry. No default-hidden ids: a board that has never
  // been configured shows everything, as it did before the menu existed.
  const { data: fetchedDefinitions = [] } = useProperties({
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
  // the memoized cards skip re-rendering on an unrelated parent pass.
  const visibleFields = useMemo(
    () => buildKanbanCardFields(fieldVisibility, propertyDefinitions),
    [fieldVisibility, propertyDefinitions]
  );

  // Asked for once here, for every card on the board.
  const { t } = useTranslation(["projects", "dates", "relations"]);
  // Every task the board has loaded, so each plug-in block reads once for all of them.
  const taskIds = useMemo(
    () => Object.values(groupedTasks).flatMap((tasks) => tasks.map((task) => task.id)),
    [groupedTasks]
  );
  const blocks = useTaskBlocks("task.card", { project, taskIds });
  const cardContext = useMemo<TaskCardContext>(
    () => ({ taskHref, showsProperty: visibleFields.showsProperty, t: t as TranslateFn, blocks }),
    [taskHref, visibleFields, t, blocks]
  );
  const dragContext = useMemo<TaskCardContext>(
    () => ({ ...cardContext, taskHref: null }),
    [cardContext]
  );

  // The people the cards' excerpts mention, asked about once for the board.
  const excerpts = useMemo(
    () =>
      visibleFields.shows("description")
        ? Object.values(groupedTasks).flatMap((tasks) =>
            tasks.flatMap((task) => task.description_excerpt ?? [])
          )
        : [],
    [groupedTasks, visibleFields]
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
            propertyDefinitions={propertyDefinitions}
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
                  cardContext={cardContext}
                  visibleFields={visibleFields}
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
          {activeTask ? (
            // The card itself, held up: it leads nowhere while it is moving.
            <div className="w-64 rounded-lg shadow-lg">
              <TaskCard task={activeTask} context={dragContext} visibleFields={visibleFields} />
            </div>
          ) : null}
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
