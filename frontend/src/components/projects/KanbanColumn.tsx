import { useDroppable } from "@dnd-kit/core";
import { SortableContext, useSortable, verticalListSortingStrategy } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { Link } from "@tanstack/react-router";
import { useVirtualizer } from "@tanstack/react-virtual";
import {
  Archive,
  Ban,
  ChevronLeft,
  ChevronRight,
  MessageSquare,
  SquareCheckBig,
} from "lucide-react";
import type { IconName } from "lucide-react/dynamic";
import { memo, useCallback, useRef } from "react";
import { useTranslation } from "react-i18next";

import type {
  TaskListRead,
  TaskPriority,
  TaskStatusRead,
} from "@/api/generated/initiativeAPI.schemas";
import { Markdown } from "@/components/Markdown";
import type { KanbanCardFields } from "@/components/projects/kanbanFields";
import type { PriorityBadgeVariant } from "@/components/projects/projectTasksConfig";
import { TaskAssigneeList } from "@/components/projects/TaskAssigneeList";
import { PropertyValueCell } from "@/components/properties/PropertyValueCell";
import { nonEmptyPropertySummaries } from "@/components/properties/propertyHelpers";
import { TagBadge } from "@/components/tags";
import { TaskChecklistProgress } from "@/components/tasks/TaskChecklistProgress";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Icon } from "@/components/ui/icon-picker";
import { formatDateTime } from "@/lib/formatDate";
import { useGuildPath } from "@/lib/guildUrl";
import { summarizeRecurrence } from "@/lib/recurrence";
import { truncateText } from "@/lib/text";
import { cn } from "@/lib/utils";
import type { TranslateFn } from "@/types/i18n";

const VIRTUALIZE_THRESHOLD = 20;
const CARD_ESTIMATE_HEIGHT = 140;
const VIRTUALIZER_OVERSCAN = 3;

interface KanbanColumnProps {
  status: TaskStatusRead;
  tasks: TaskListRead[];
  canWrite: boolean;
  priorityVariant: Record<TaskPriority, PriorityBadgeVariant>;
  taskHref: (taskId: number) => string;
  canOpenTask: boolean;
  collapsed: boolean;
  onToggleCollapse: (statusId: number) => void;
  taskCount: number;
  visibleFields: KanbanCardFields;
  className?: string;
  onArchiveDoneTasks?: (statusId: number) => void;
  isArchiving?: boolean;
}

export const KanbanColumn = ({
  status,
  tasks,
  canWrite,
  priorityVariant,
  taskHref,
  canOpenTask,
  collapsed,
  onToggleCollapse,
  taskCount,
  visibleFields,
  className,
  onArchiveDoneTasks,
  isArchiving,
}: KanbanColumnProps) => {
  const { t } = useTranslation("projects");
  const { setNodeRef: setDroppableRef, isOver } = useDroppable({
    id: `column-${status.id}`,
    data: { type: "column", statusId: status.id },
  });

  const enableVirtualization = tasks.length > VIRTUALIZE_THRESHOLD;
  const scrollContainerRef = useRef<HTMLDivElement | null>(null);

  const mergedRef = useCallback(
    (el: HTMLDivElement | null) => {
      setDroppableRef(el);
      scrollContainerRef.current = el;
    },
    [setDroppableRef]
  );

  const virtualizer = useVirtualizer({
    count: tasks.length,
    getScrollElement: () => scrollContainerRef.current,
    estimateSize: () => CARD_ESTIMATE_HEIGHT,
    overscan: VIRTUALIZER_OVERSCAN,
    enabled: enableVirtualization,
  });

  const virtualItems = enableVirtualization ? virtualizer.getVirtualItems() : [];
  const paddingTop = virtualItems.length > 0 ? virtualItems[0].start : 0;
  const paddingBottom =
    virtualItems.length > 0
      ? virtualizer.getTotalSize() - virtualItems[virtualItems.length - 1].end
      : 0;

  const taskIds = tasks.map((task) => task.id.toString());

  return (
    <div
      className={cn(
        "flex h-full flex-col overflow-hidden rounded-lg border bg-card shadow-sm transition-colors",
        collapsed && "items-center text-center",
        className
      )}
    >
      <div
        aria-hidden="true"
        className="h-1 w-full shrink-0"
        style={{ backgroundColor: status.color }}
      />
      {collapsed ? (
        <CollapsedHeader
          status={status}
          taskCount={taskCount}
          onToggleCollapse={onToggleCollapse}
        />
      ) : (
        <ExpandedHeader status={status} taskCount={taskCount} onToggleCollapse={onToggleCollapse} />
      )}
      <div
        ref={mergedRef}
        className={cn(
          "h-full w-full transition-colors",
          collapsed
            ? "flex flex-1 items-center justify-center px-2"
            : "scrollbar-thin flex-1 space-y-3 overflow-y-auto p-3 pr-2",
          isOver ? "bg-muted/40" : null
        )}
      >
        {collapsed ? (
          <span className="text-muted-foreground text-xs">{t("kanban.dropHere")}</span>
        ) : tasks.length === 0 ? (
          <p className="text-muted-foreground text-sm">{t("kanban.noTasks")}</p>
        ) : (
          <SortableContext items={taskIds} strategy={verticalListSortingStrategy}>
            {enableVirtualization ? (
              <>
                {paddingTop > 0 && <div style={{ height: paddingTop }} />}
                {virtualItems.map((virtualRow) => {
                  const task = tasks[virtualRow.index];
                  return canWrite ? (
                    <KanbanTaskCardSortable
                      key={task.id}
                      data-index={virtualRow.index}
                      ref={virtualizer.measureElement}
                      task={task}
                      priorityVariant={priorityVariant}
                      taskHref={taskHref}
                      canOpenTask={canOpenTask}
                      visibleFields={visibleFields}
                    />
                  ) : (
                    <KanbanTaskCardPlain
                      key={task.id}
                      data-index={virtualRow.index}
                      ref={virtualizer.measureElement}
                      task={task}
                      priorityVariant={priorityVariant}
                      taskHref={taskHref}
                      canOpenTask={canOpenTask}
                      visibleFields={visibleFields}
                    />
                  );
                })}
                {paddingBottom > 0 && <div style={{ height: paddingBottom }} />}
              </>
            ) : (
              tasks.map((task) => (
                <KanbanTaskCard
                  key={task.id}
                  task={task}
                  canWrite={canWrite}
                  priorityVariant={priorityVariant}
                  taskHref={taskHref}
                  canOpenTask={canOpenTask}
                  visibleFields={visibleFields}
                />
              ))
            )}
          </SortableContext>
        )}
      </div>
      {!collapsed && status.category === "done" && onArchiveDoneTasks && (
        <div className="border-t p-2" data-kanban-scroll-lock="true">
          <Button
            variant="ghost"
            size="sm"
            className="w-full text-xs"
            onClick={() => onArchiveDoneTasks(status.id)}
            disabled={isArchiving}
          >
            <Archive className="h-3.5 w-3.5" />
            {isArchiving ? t("kanban.archiving") : t("kanban.archiveDone")}
          </Button>
        </div>
      )}
    </div>
  );
};

const ExpandedHeader = ({
  status,
  taskCount,
  onToggleCollapse,
}: {
  status: TaskStatusRead;
  taskCount: number;
  onToggleCollapse: (statusId: number) => void;
}) => {
  const { t } = useTranslation("projects");
  return (
    <div
      className="sticky top-0 z-20 flex items-center justify-between gap-2 border-b bg-card px-3 py-2"
      data-kanban-scroll-lock="true"
    >
      <div className="flex min-w-0 items-center gap-2">
        <Icon
          name={status.icon as IconName}
          style={{ color: status.color }}
          className="h-6 w-6 shrink-0"
        />
        <div className="min-w-0">
          <p className="truncate font-semibold text-lg leading-none">{status.name}</p>
          <p className="inline-flex items-center gap-1 text-muted-foreground text-xs">
            <SquareCheckBig className="h-3 w-3" /> {t("kanban.taskCount", { count: taskCount })}
          </p>
        </div>
      </div>
      <Button
        type="button"
        variant="ghost"
        size="icon"
        className="h-7 w-7 shrink-0 text-muted-foreground"
        onClick={() => onToggleCollapse(status.id)}
        aria-label={t("kanban.collapse", { name: status.name })}
      >
        <ChevronLeft className="h-4 w-4" />
      </Button>
    </div>
  );
};

const CollapsedHeader = ({
  status,
  taskCount,
  onToggleCollapse,
}: {
  status: TaskStatusRead;
  taskCount: number;
  onToggleCollapse: (statusId: number) => void;
}) => {
  const { t } = useTranslation("projects");
  return (
    <div className="flex flex-col items-center gap-3 py-4" data-kanban-scroll-lock="true">
      <Button
        type="button"
        variant="ghost"
        size="icon"
        className="h-7 w-7 text-muted-foreground"
        onClick={() => onToggleCollapse(status.id)}
        aria-label={t("kanban.expand", { name: status.name })}
      >
        <ChevronRight className="h-4 w-4" />
      </Button>
      <Icon name={status.icon as IconName} style={{ color: status.color }} className="h-4 w-4" />
      <div className="flex h-16 items-center justify-center">
        <span className="rotate-90 whitespace-nowrap font-semibold text-muted-foreground text-xs tracking-wide">
          {status.name}
        </span>
      </div>
      <span className="inline-flex items-center gap-1 text-muted-foreground text-xs">
        <SquareCheckBig className="h-3 w-3" /> {taskCount}
      </span>
    </div>
  );
};

// --- Card content (pure display, memoized) ---

interface KanbanCardContentProps {
  task: TaskListRead;
  priorityVariant: Record<TaskPriority, PriorityBadgeVariant>;
  taskHref: (taskId: number) => string;
  canOpenTask: boolean;
  visibleFields: KanbanCardFields;
}

const KanbanCardContent = memo(
  function KanbanCardContent({
    task,
    priorityVariant,
    taskHref,
    canOpenTask,
    visibleFields,
  }: KanbanCardContentProps) {
    const { t } = useTranslation(["projects", "dates"]);
    const { t: tRelations } = useTranslation("relations");
    const gp = useGuildPath();

    const { shows, showsProperty } = visibleFields;

    const recurrenceSummary = task.recurrence
      ? summarizeRecurrence(
          task.recurrence,
          {
            referenceDate: task.start_date || task.due_date,
            strategy: task.recurrence_strategy,
          },
          t as TranslateFn
        )
      : null;
    const recurrenceText = recurrenceSummary ? truncateText(recurrenceSummary, 80) : null;
    // `formatDateTime` rather than `toLocaleString`: it is what every other
    // timestamp in the app goes through, so it honours the reader's 12/24-hour
    // choice and reads the same way ("Aug 3, 2026, 21:15").
    const formattedStart = formatDateTime(task.start_date);
    const formattedDue = formatDateTime(task.due_date);
    const commentCount = task.comment_count ?? 0;
    const blockedCount = task.blocked_by_open_count ?? 0;
    // A property is turned off by its own menu entry, resolved by id.
    const visibleProperties = nonEmptyPropertySummaries(task.properties).filter((summary) =>
      showsProperty(summary.property_id)
    );

    return (
      <>
        <div className="flex w-full min-w-0 flex-col items-start gap-1 text-left">
          {canOpenTask ? (
            // Only the title opens the task: the rest of the card is the card,
            // and a real link means middle-click and "open in new tab" work.
            <Link
              to={taskHref(task.id)}
              draggable={false}
              className="wrap-break-word w-full min-w-0 rounded-sm font-medium underline-offset-4 outline-none hover:underline focus-visible:ring-1 focus-visible:ring-ring"
            >
              {task.title}
            </Link>
          ) : (
            <p className="wrap-break-word w-full min-w-0 font-medium opacity-70">{task.title}</p>
          )}
          {shows("description") && task.description ? (
            <Markdown content={task.description} className="line-clamp-2 w-full min-w-0" mentions />
          ) : null}
          <div className="wrap-break-word w-full min-w-0 space-y-1 text-muted-foreground text-xs">
            {shows("assignees") && task.assignees.length > 0 ? (
              <TaskAssigneeList assignees={task.assignees} className="text-xs" />
            ) : null}
            {shows("startDate") && formattedStart ? (
              <p>{t("kanban.starts", { date: formattedStart })}</p>
            ) : null}
            {shows("dueDate") && formattedDue ? (
              <p>{t("kanban.due", { date: formattedDue })}</p>
            ) : null}
            {shows("recurrence") && recurrenceText ? <p>{recurrenceText}</p> : null}
          </div>
          {shows("checklist") ? (
            <TaskChecklistProgress progress={task.checklist_progress} className="w-full pt-1" />
          ) : null}
        </div>
        <div className="flex min-w-0 flex-wrap gap-2">
          {shows("priority") ? (
            <Badge variant={priorityVariant[task.priority]}>
              {t("kanban.priority", { priority: task.priority.replace("_", " ") })}
            </Badge>
          ) : null}
          {shows("comments") && commentCount > 0 ? (
            <Badge variant="outline" className="inline-flex items-center gap-1 text-xs">
              <MessageSquare className="h-3.5 w-3.5" aria-hidden="true" />
              {commentCount}
            </Badge>
          ) : null}
          {/* The signal the retired Blocked column used to give, back on the
              card and keeping itself current: it goes when the last thing
              holding this up is finished, with nobody moving anything. */}
          {shows("blockers") && blockedCount > 0 ? (
            <Badge
              variant="outline"
              className="inline-flex items-center gap-1 border-warning/40 text-warning text-xs"
              title={tRelations("blockers.label", { count: blockedCount })}
            >
              <Ban className="h-3.5 w-3.5" aria-hidden="true" />
              {blockedCount}
            </Badge>
          ) : null}
          {shows("tags") &&
            task.tags &&
            task.tags.length > 0 &&
            task.tags.map((tag) => (
              <TagBadge key={tag.id} tag={tag} size="sm" to={gp(`/tags/${tag.id}`)} />
            ))}
          {visibleProperties.map((summary) => (
            <PropertyValueCell key={summary.property_id} summary={summary} variant="chip" />
          ))}
        </div>
      </>
    );
  },
  (prev, next) =>
    prev.task === next.task &&
    prev.canOpenTask === next.canOpenTask &&
    prev.visibleFields === next.visibleFields
);

// --- Sortable card (with DnD, used in virtualized mode) ---

interface KanbanTaskCardVirtualProps {
  task: TaskListRead;
  priorityVariant: Record<TaskPriority, PriorityBadgeVariant>;
  taskHref: (taskId: number) => string;
  canOpenTask: boolean;
  visibleFields: KanbanCardFields;
  "data-index": number;
}

const KanbanTaskCardSortable = memo(
  function KanbanTaskCardSortable({
    task,
    priorityVariant,
    taskHref,
    canOpenTask,
    visibleFields,
    "data-index": dataIndex,
    ref,
  }: KanbanTaskCardVirtualProps & { ref?: React.Ref<HTMLDivElement> }) {
    const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
      id: task.id.toString(),
      data: { type: "task", statusId: task.task_status_id },
    });

    const mergedRef = useCallback(
      (el: HTMLDivElement | null) => {
        setNodeRef(el);
        if (typeof ref === "function") {
          ref(el);
        } else if (ref && typeof ref === "object") {
          (ref as React.MutableRefObject<HTMLDivElement | null>).current = el;
        }
      },
      [setNodeRef, ref]
    );

    const style = {
      transform: CSS.Transform.toString(transform),
      transition,
      opacity: isDragging ? 0.25 : undefined,
    };

    return (
      <div
        ref={mergedRef}
        data-index={dataIndex}
        style={style}
        {...attributes}
        {...listeners}
        className={cn(
          "space-y-3 rounded-lg border bg-card p-3 shadow-sm",
          task.archived_at !== null && "opacity-50"
        )}
        data-kanban-scroll-lock="true"
      >
        <KanbanCardContent
          task={task}
          priorityVariant={priorityVariant}
          taskHref={taskHref}
          canOpenTask={canOpenTask}
          visibleFields={visibleFields}
        />
      </div>
    );
  },
  (prev, next) =>
    prev.task === next.task &&
    prev.canOpenTask === next.canOpenTask &&
    prev.visibleFields === next.visibleFields
);

// --- Plain card (no DnD hooks, used in virtualized mode when !canWrite) ---

const KanbanTaskCardPlain = memo(
  function KanbanTaskCardPlain({
    task,
    priorityVariant,
    taskHref,
    canOpenTask,
    visibleFields,
    "data-index": dataIndex,
    ref,
  }: KanbanTaskCardVirtualProps & { ref?: React.Ref<HTMLDivElement> }) {
    return (
      <div
        ref={ref}
        data-index={dataIndex}
        className={cn(
          "space-y-3 rounded-lg border bg-card p-3 shadow-sm",
          task.archived_at !== null && "opacity-50"
        )}
        data-kanban-scroll-lock="true"
      >
        <KanbanCardContent
          task={task}
          priorityVariant={priorityVariant}
          taskHref={taskHref}
          canOpenTask={canOpenTask}
          visibleFields={visibleFields}
        />
      </div>
    );
  },
  (prev, next) =>
    prev.task === next.task &&
    prev.canOpenTask === next.canOpenTask &&
    prev.visibleFields === next.visibleFields
);

// --- Original non-virtualized card (used for small lists) ---

interface KanbanTaskCardProps {
  task: TaskListRead;
  canWrite: boolean;
  priorityVariant: Record<TaskPriority, PriorityBadgeVariant>;
  taskHref: (taskId: number) => string;
  canOpenTask: boolean;
  visibleFields: KanbanCardFields;
}

const KanbanTaskCard = ({
  task,
  canWrite,
  priorityVariant,
  taskHref,
  canOpenTask,
  visibleFields,
}: KanbanTaskCardProps) => {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: task.id.toString(),
    data: { type: "task", statusId: task.task_status_id },
    disabled: !canWrite,
  });

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.25 : undefined,
  };

  return (
    <div
      ref={setNodeRef}
      style={style}
      {...attributes}
      {...listeners}
      className={cn(
        "space-y-3 rounded-lg border bg-card p-3 shadow-sm",
        task.archived_at !== null && "opacity-50"
      )}
      data-kanban-scroll-lock="true"
    >
      <KanbanCardContent
        task={task}
        priorityVariant={priorityVariant}
        taskHref={taskHref}
        canOpenTask={canOpenTask}
        visibleFields={visibleFields}
      />
    </div>
  );
};
