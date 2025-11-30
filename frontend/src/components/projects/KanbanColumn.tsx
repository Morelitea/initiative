import { useDroppable } from "@dnd-kit/core";
import { SortableContext, useSortable, verticalListSortingStrategy } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { ChevronLeft, ChevronRight, SquareCheckBig, MessageSquare } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { ProjectTaskStatus, Task, TaskPriority } from "@/types/api";
import { truncateText } from "@/lib/text";
import { summarizeRecurrence } from "@/lib/recurrence";
import { TaskAssigneeList } from "@/components/projects/TaskAssigneeList";
import { cn } from "@/lib/utils";

interface KanbanColumnProps {
  status: ProjectTaskStatus;
  tasks: Task[];
  canWrite: boolean;
  priorityVariant: Record<TaskPriority, "default" | "secondary" | "destructive">;
  onTaskClick: (taskId: number) => void;
  canOpenTask: boolean;
  collapsed: boolean;
  onToggleCollapse: (statusId: number) => void;
  taskCount: number;
}

export const KanbanColumn = ({
  status,
  tasks,
  canWrite,
  priorityVariant,
  onTaskClick,
  canOpenTask,
  collapsed,
  onToggleCollapse,
  taskCount,
}: KanbanColumnProps) => {
  const { setNodeRef, isOver } = useDroppable({
    id: `column-${status.id}`,
    data: { type: "column", statusId: status.id },
  });

  return (
    <div
      className={cn(
        "bg-card flex h-full flex-col rounded-lg border shadow-sm transition-colors",
        collapsed && "items-center text-center"
      )}
    >
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
        ref={setNodeRef}
        className={cn(
          "max-h-[70vh] min-h-[70vh] w-full transition-colors",
          collapsed
            ? "flex flex-1 items-center justify-center px-2"
            : "flex-1 space-y-3 overflow-y-auto p-3 pr-2",
          isOver ? "bg-muted/40" : null
        )}
      >
        {collapsed ? (
          <span className="text-muted-foreground text-xs">Drop tasks here</span>
        ) : tasks.length === 0 ? (
          <p className="text-muted-foreground text-sm">No tasks yet.</p>
        ) : (
          <SortableContext
            items={tasks.map((task) => task.id.toString())}
            strategy={verticalListSortingStrategy}
          >
            {tasks.map((task) => (
              <KanbanTaskCard
                key={task.id}
                task={task}
                canWrite={canWrite}
                priorityVariant={priorityVariant}
                onTaskClick={onTaskClick}
                canOpenTask={canOpenTask}
              />
            ))}
          </SortableContext>
        )}
      </div>
    </div>
  );
};

const ExpandedHeader = ({
  status,
  taskCount,
  onToggleCollapse,
}: {
  status: ProjectTaskStatus;
  taskCount: number;
  onToggleCollapse: (statusId: number) => void;
}) => (
  <div
    className="bg-card sticky top-0 z-20 flex items-center justify-between gap-2 border-b px-3 py-2"
    style={{ borderTopLeftRadius: "0.5rem", borderTopRightRadius: "0.5rem" }}
    data-kanban-scroll-lock="true"
  >
    <div>
      <p className="text-lg leading-none font-semibold">{status.name}</p>
      <p className="text-muted-foreground inline-flex items-center gap-1 text-xs">
        <SquareCheckBig className="h-3 w-3" /> {taskCount} task{taskCount === 1 ? "" : "s"}
      </p>
    </div>
    <Button
      type="button"
      variant="ghost"
      size="icon"
      className="text-muted-foreground h-7 w-7"
      onClick={() => onToggleCollapse(status.id)}
      aria-label={`Collapse ${status.name}`}
    >
      <ChevronLeft className="h-4 w-4" />
    </Button>
  </div>
);

const CollapsedHeader = ({
  status,
  taskCount,
  onToggleCollapse,
}: {
  status: ProjectTaskStatus;
  taskCount: number;
  onToggleCollapse: (statusId: number) => void;
}) => (
  <div className="flex flex-col items-center gap-3 py-4" data-kanban-scroll-lock="true">
    <Button
      type="button"
      variant="ghost"
      size="icon"
      className="text-muted-foreground h-7 w-7"
      onClick={() => onToggleCollapse(status.id)}
      aria-label={`Expand ${status.name}`}
    >
      <ChevronRight className="h-4 w-4" />
    </Button>
    <div className="flex h-16 items-center justify-center">
      <span className="text-muted-foreground rotate-90 text-xs font-semibold tracking-wide whitespace-nowrap">
        {status.name}
      </span>
    </div>
    <span className="text-muted-foreground inline-flex items-center gap-1 text-xs">
      <SquareCheckBig className="h-3 w-3" /> {taskCount}
    </span>
  </div>
);

interface KanbanTaskCardProps {
  task: Task;
  canWrite: boolean;
  priorityVariant: Record<TaskPriority, "default" | "secondary" | "destructive">;
  onTaskClick: (taskId: number) => void;
  canOpenTask: boolean;
}

const KanbanTaskCard = ({
  task,
  canWrite,
  priorityVariant,
  onTaskClick,
  canOpenTask,
}: KanbanTaskCardProps) => {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: task.id.toString(),
    data: { type: "task", statusId: task.task_status_id },
    disabled: !canWrite,
  });

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.6 : undefined,
  };

  const recurrenceSummary = task.recurrence
    ? summarizeRecurrence(task.recurrence, { referenceDate: task.start_date || task.due_date })
    : null;
  const recurrenceText = recurrenceSummary ? truncateText(recurrenceSummary, 80) : null;
  const formattedStart = task.start_date ? new Date(task.start_date).toLocaleString() : null;
  const formattedDue = task.due_date ? new Date(task.due_date).toLocaleString() : null;
  const commentCount = task.comment_count ?? 0;

  return (
    <div
      ref={setNodeRef}
      style={style}
      {...attributes}
      {...listeners}
      className="bg-card space-y-3 rounded-lg border p-3 shadow-sm"
      data-kanban-scroll-lock="true"
    >
      <button
        type="button"
        onClick={(event) => {
          event.stopPropagation();
          if (!canOpenTask) {
            return;
          }
          onTaskClick(task.id);
        }}
        disabled={!canOpenTask}
        className={`flex w-full flex-col items-start gap-1 text-left ${
          canOpenTask ? "" : "cursor-not-allowed opacity-70"
        }`}
      >
        <p className="font-medium">{task.title}</p>
        {task.description ? (
          <p className="text-muted-foreground text-xs">{truncateText(task.description, 80)}</p>
        ) : null}
        <div className="text-muted-foreground space-y-1 text-xs">
          {task.assignees.length > 0 ? (
            <TaskAssigneeList assignees={task.assignees} className="text-xs" />
          ) : null}
          {formattedStart ? <p>Starts: {formattedStart}</p> : null}
          {formattedDue ? <p>Due: {formattedDue}</p> : null}
          {recurrenceText ? <p>{recurrenceText}</p> : null}
        </div>
      </button>
      <div className="flex flex-wrap gap-2">
        <Badge variant={priorityVariant[task.priority]}>
          Priority: {task.priority.replace("_", " ")}
        </Badge>
        {commentCount > 0 ? (
          <Badge variant="outline" className="inline-flex items-center gap-1 text-xs">
            <MessageSquare className="h-3.5 w-3.5" aria-hidden="true" />
            {commentCount}
          </Badge>
        ) : null}
      </div>
    </div>
  );
};
