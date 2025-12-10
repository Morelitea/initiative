import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { isAxiosError } from "axios";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import {
  DndContext,
  PointerSensor,
  closestCenter,
  type DragEndEvent,
  useSensor,
  useSensors,
} from "@dnd-kit/core";
import {
  SortableContext,
  arrayMove,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { GripVertical, Loader2, Trash2, SquareCheck } from "lucide-react";

import { apiClient } from "@/api/client";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import type { TaskSubtask, TaskSubtaskProgress } from "@/types/api";
import { TaskChecklistProgress } from "@/components/tasks/TaskChecklistProgress";

type TaskChecklistProps = {
  taskId: number;
  projectId?: number | null;
  canEdit: boolean;
};

type UpdatePayload = {
  subtaskId: number;
  data: Partial<Pick<TaskSubtask, "content" | "is_completed">>;
};

export const TaskChecklist = ({ taskId, projectId, canEdit }: TaskChecklistProps) => {
  const queryClient = useQueryClient();
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [newContent, setNewContent] = useState("");
  const [contentDrafts, setContentDrafts] = useState<Record<number, string>>({});

  const subtasksQueryKey = useMemo(() => ["tasks", taskId, "subtasks"], [taskId]);

  const invalidateRelatedData = useCallback(() => {
    void queryClient.invalidateQueries({ queryKey: subtasksQueryKey });
    void queryClient.invalidateQueries({ queryKey: ["task", taskId] });
    if (Number.isFinite(projectId)) {
      void queryClient.invalidateQueries({ queryKey: ["tasks", projectId] });
    }
    void queryClient.invalidateQueries({ queryKey: ["tasks", "global"] });
  }, [projectId, queryClient, subtasksQueryKey, taskId]);

  const subtasksQuery = useQuery<TaskSubtask[]>({
    queryKey: subtasksQueryKey,
    queryFn: async () => {
      const response = await apiClient.get<TaskSubtask[]>(`/tasks/${taskId}/subtasks`);
      return response.data;
    },
  });

  const [localSubtasks, setLocalSubtasks] = useState<TaskSubtask[]>([]);

  useEffect(() => {
    const sorted = (subtasksQuery.data ?? []).slice().sort((a, b) => {
      if (a.position === b.position) {
        return a.id - b.id;
      }
      return a.position - b.position;
    });
    setLocalSubtasks(sorted);
  }, [subtasksQuery.data]);

  const progress: TaskSubtaskProgress | null = useMemo(() => {
    const total = localSubtasks.length;
    if (total === 0) {
      return null;
    }
    const completed = localSubtasks.filter((item) => item.is_completed).length;
    return { completed, total };
  }, [localSubtasks]);

  const parseErrorMessage = (error: unknown, fallback: string) => {
    if (isAxiosError(error)) {
      return (error.response?.data?.detail as string) ?? fallback;
    }
    if (error instanceof Error) {
      return error.message;
    }
    return fallback;
  };

  const createSubtask = useMutation({
    mutationFn: async (content: string) => {
      const response = await apiClient.post<TaskSubtask>(`/tasks/${taskId}/subtasks`, {
        content,
      });
      return response.data;
    },
    onSuccess: () => {
      setNewContent("");
      inputRef.current?.focus();
      invalidateRelatedData();
      toast.success("Checklist item added");
    },
    onError: (error) => {
      toast.error(parseErrorMessage(error, "Unable to add checklist item. Please try again."));
    },
  });

  const updateSubtask = useMutation({
    mutationFn: async ({ subtaskId, data }: UpdatePayload) => {
      const response = await apiClient.patch<TaskSubtask>(`/subtasks/${subtaskId}`, data);
      return response.data;
    },
    onSuccess: (_response, variables) => {
      if (variables.data.content !== undefined) {
        setContentDrafts((previous) => {
          const next = { ...previous };
          delete next[variables.subtaskId];
          return next;
        });
      }
      invalidateRelatedData();
    },
    onError: (error) => {
      toast.error(parseErrorMessage(error, "Unable to update checklist item. Please try again."));
    },
  });

  const deleteSubtask = useMutation({
    mutationFn: async (subtaskId: number) => {
      await apiClient.delete(`/subtasks/${subtaskId}`);
    },
    onSuccess: (_response, subtaskId) => {
      setContentDrafts((previous) => {
        const next = { ...previous };
        delete next[subtaskId];
        return next;
      });
      invalidateRelatedData();
      toast.success("Checklist item deleted");
    },
    onError: (error) => {
      toast.error(parseErrorMessage(error, "Unable to delete checklist item. Please try again."));
    },
  });

  const reorderSubtasks = useMutation({
    mutationFn: async (items: { id: number; position: number }[]) => {
      const response = await apiClient.put<TaskSubtask[]>(`/tasks/${taskId}/subtasks/order`, {
        items,
      });
      return response.data;
    },
    onSuccess: () => {
      invalidateRelatedData();
    },
    onError: (error) => {
      toast.error(parseErrorMessage(error, "Unable to reorder checklist items. Please try again."));
    },
  });

  const handleAdd = () => {
    if (!canEdit || createSubtask.isPending) {
      return;
    }
    const trimmed = newContent.trim();
    if (!trimmed) {
      return;
    }
    createSubtask.mutate(trimmed);
  };

  const handleToggle = (item: TaskSubtask, checked: boolean) => {
    if (!canEdit) {
      return;
    }
    setLocalSubtasks((previous) =>
      previous.map((subtask) =>
        subtask.id === item.id ? { ...subtask, is_completed: checked } : subtask
      )
    );
    updateSubtask.mutate({
      subtaskId: item.id,
      data: { is_completed: checked },
    });
  };

  const handleContentBlur = (item: TaskSubtask) => {
    const draftValue = contentDrafts[item.id];
    if (draftValue === undefined) {
      return;
    }
    const trimmed = draftValue.trim();
    if (!trimmed) {
      setContentDrafts((previous) => {
        const next = { ...previous };
        delete next[item.id];
        return next;
      });
      toast.error("Checklist content cannot be empty.");
      return;
    }
    if (trimmed === item.content) {
      setContentDrafts((previous) => {
        const next = { ...previous };
        delete next[item.id];
        return next;
      });
      return;
    }
    setLocalSubtasks((previous) =>
      previous.map((subtask) =>
        subtask.id === item.id ? { ...subtask, content: trimmed } : subtask
      )
    );
    updateSubtask.mutate({
      subtaskId: item.id,
      data: { content: trimmed },
    });
  };

  const sensors = useSensors(
    useSensor(PointerSensor, {
      activationConstraint: { distance: 4 },
    })
  );

  const handleDragEnd = useCallback(
    (event: DragEndEvent) => {
      if (!canEdit || reorderSubtasks.isPending) {
        return;
      }
      const { active, over } = event;
      if (!over || active.id === over.id) {
        return;
      }
      const activeId = Number(active.id);
      const overId = Number(over.id);
      const oldIndex = localSubtasks.findIndex((item) => item.id === activeId);
      const newIndex = localSubtasks.findIndex((item) => item.id === overId);
      if (oldIndex === -1 || newIndex === -1) {
        return;
      }
      const next = arrayMove(localSubtasks, oldIndex, newIndex);
      setLocalSubtasks(next);
      reorderSubtasks.mutate(next.map((item, position) => ({ id: item.id, position })));
    },
    [canEdit, localSubtasks, reorderSubtasks]
  );

  const reorderDisabled = !canEdit || reorderSubtasks.isPending;

  return (
    <Card className="shadow-sm">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <SquareCheck className="text-muted-foreground h-4 w-4" aria-hidden="true" />
          Subtasks
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {subtasksQuery.isLoading ? (
          <p className="text-muted-foreground inline-flex items-center gap-2 text-sm">
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
            Loading checklist…
          </p>
        ) : subtasksQuery.isError ? (
          <p className="text-destructive text-sm">Unable to load checklist items right now.</p>
        ) : localSubtasks.length === 0 ? (
          <p className="text-muted-foreground text-sm">
            No checklist items yet. {canEdit ? "Add your first step below." : ""}
          </p>
        ) : (
          <div className="space-y-3">
            <TaskChecklistProgress progress={progress} />
            <DndContext
              sensors={sensors}
              collisionDetection={closestCenter}
              onDragEnd={handleDragEnd}
            >
              <SortableContext
                items={localSubtasks.map((item) => item.id.toString())}
                strategy={verticalListSortingStrategy}
              >
                <ul className="space-y-2">
                  {localSubtasks.map((item) => (
                    <ChecklistItemRow
                      key={item.id}
                      item={item}
                      canEdit={canEdit}
                      reorderDisabled={reorderDisabled}
                      isUpdating={updateSubtask.isPending}
                      isDeleting={deleteSubtask.isPending}
                      contentValue={contentDrafts[item.id] ?? item.content}
                      onContentChange={(value) =>
                        setContentDrafts((previous) => ({
                          ...previous,
                          [item.id]: value,
                        }))
                      }
                      onContentBlur={() => handleContentBlur(item)}
                      onToggle={(value) => handleToggle(item, value)}
                      onDelete={() => deleteSubtask.mutate(item.id)}
                    />
                  ))}
                </ul>
              </SortableContext>
            </DndContext>
          </div>
        )}

        <div className="flex gap-2">
          <Input
            ref={inputRef}
            placeholder={canEdit ? "Add checklist item" : "Read-only"}
            value={newContent}
            onChange={(event) => setNewContent(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault();
                handleAdd();
              }
            }}
            disabled={!canEdit || createSubtask.isPending}
          />
          <Button type="button" onClick={handleAdd} disabled={!canEdit || createSubtask.isPending}>
            Add
          </Button>
        </div>
        {!canEdit ? (
          <p className="text-muted-foreground text-xs">
            You only have read access, so checklist changes are disabled.
          </p>
        ) : null}
      </CardContent>
    </Card>
  );
};

type ChecklistItemRowProps = {
  item: TaskSubtask;
  canEdit: boolean;
  reorderDisabled: boolean;
  isUpdating: boolean;
  isDeleting: boolean;
  contentValue: string;
  onContentChange: (value: string) => void;
  onContentBlur: () => void;
  onToggle: (checked: boolean) => void;
  onDelete: () => void;
};

const ChecklistItemRow = ({
  item,
  canEdit,
  reorderDisabled,
  isUpdating,
  isDeleting,
  contentValue,
  onContentChange,
  onContentBlur,
  onToggle,
  onDelete,
}: ChecklistItemRowProps) => {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: item.id.toString(),
    disabled: reorderDisabled,
  });

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
  };

  return (
    <li
      ref={setNodeRef}
      style={style}
      className={`bg-muted/30 flex flex-col gap-2 rounded-md border px-3 py-2 text-sm md:flex-row md:items-center md:gap-3 ${
        isDragging ? "opacity-80 shadow-sm" : ""
      }`}
    >
      <div className="flex flex-1 items-center gap-2">
        {canEdit ? (
          <button
            type="button"
            className="text-muted-foreground mt-1"
            disabled={reorderDisabled}
            aria-label="Reorder checklist item"
            {...attributes}
            {...listeners}
          >
            <GripVertical className="-mt-1 h-4 w-4" />
          </button>
        ) : null}
        <Checkbox
          checked={item.is_completed}
          onCheckedChange={(value) => onToggle(Boolean(value))}
          disabled={!canEdit || isUpdating}
          aria-label={item.is_completed ? "Mark subtask as incomplete" : "Mark subtask as complete"}
        />
        <Input
          value={contentValue}
          onChange={(event) => onContentChange(event.target.value)}
          onBlur={onContentBlur}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              event.preventDefault();
              event.currentTarget.blur();
            }
          }}
          disabled={!canEdit || isUpdating}
          className={item.is_completed ? "line-through" : undefined}
        />
      </div>
      {canEdit ? (
        <div className="flex items-center gap-1 self-end md:self-auto">
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="text-destructive hover:text-destructive"
            disabled={isDeleting}
            onClick={onDelete}
          >
            <Trash2 className="h-4 w-4" />
          </Button>
        </div>
      ) : null}
    </li>
  );
};
