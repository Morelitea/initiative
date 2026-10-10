import { useDroppable } from "@dnd-kit/core";
import { SortableContext, useSortable, verticalListSortingStrategy } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { useVirtualizer } from "@tanstack/react-virtual";
import { Archive, ChevronLeft, ChevronRight, SquareCheckBig } from "lucide-react";
import type { IconName } from "lucide-react/dynamic";
import { memo, useCallback, useRef } from "react";
import { useTranslation } from "react-i18next";

import type { TaskListRead, TaskStatusRead } from "@/api/generated/initiativeAPI.schemas";
import { Button } from "@/components/ui/button";
import { Icon } from "@/components/ui/icon-picker";
import { TASK_CARD } from "@/lib/layouts/tasks";
import { type LayoutContext, LayoutTree } from "@/lib/layouts/tree";
import { cn } from "@/lib/utils";

const VIRTUALIZE_THRESHOLD = 20;
const CARD_ESTIMATE_HEIGHT = 140;
const VIRTUALIZER_OVERSCAN = 3;

interface KanbanColumnProps {
  status: TaskStatusRead;
  tasks: TaskListRead[];
  canWrite: boolean;
  /** What every card on the board shares, made once for the board. */
  view: LayoutContext;
  collapsed: boolean;
  onToggleCollapse: (statusId: number) => void;
  taskCount: number;
  className?: string;
  onArchiveDoneTasks?: (statusId: number) => void;
  isArchiving?: boolean;
}

export const KanbanColumn = ({
  status,
  tasks,
  canWrite,
  view,
  collapsed,
  onToggleCollapse,
  taskCount,
  className,
  onArchiveDoneTasks,
  isArchiving,
}: KanbanColumnProps) => {
  const { t } = useTranslation(["projects", "common"]);
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
                      view={view}
                    />
                  ) : (
                    <KanbanTaskCardPlain
                      key={task.id}
                      data-index={virtualRow.index}
                      ref={virtualizer.measureElement}
                      task={task}
                      view={view}
                    />
                  );
                })}
                {paddingBottom > 0 && <div style={{ height: paddingBottom }} />}
              </>
            ) : (
              tasks.map((task) => (
                <KanbanTaskCard key={task.id} task={task} canWrite={canWrite} view={view} />
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
            {isArchiving ? t("common:toolSettings.archive.archiving") : t("kanban.archiveDone")}
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

// --- Sortable card (with DnD, used in virtualized mode) ---

interface KanbanTaskCardVirtualProps {
  task: TaskListRead;
  view: LayoutContext;
  "data-index": number;
}

const KanbanTaskCardSortable = memo(
  function KanbanTaskCardSortable({
    task,
    view,
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
        <LayoutTree node={view.card ?? TASK_CARD} item={task} view={view} />
      </div>
    );
  },
  (prev, next) => prev.task === next.task && prev.view === next.view
);

// --- Plain card (no DnD hooks, used in virtualized mode when !canWrite) ---

const KanbanTaskCardPlain = memo(
  function KanbanTaskCardPlain({
    task,
    view,
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
        <LayoutTree node={view.card ?? TASK_CARD} item={task} view={view} />
      </div>
    );
  },
  (prev, next) => prev.task === next.task && prev.view === next.view
);

// --- Original non-virtualized card (used for small lists) ---

interface KanbanTaskCardProps {
  task: TaskListRead;
  canWrite: boolean;
  view: LayoutContext;
}

const KanbanTaskCard = ({ task, canWrite, view }: KanbanTaskCardProps) => {
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
      <LayoutTree node={view.card ?? TASK_CARD} item={task} view={view} />
    </div>
  );
};
