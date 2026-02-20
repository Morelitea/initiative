import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { isAxiosError } from "axios";
import { useMutation, useQuery } from "@tanstack/react-query";
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
import { GripVertical, Loader2, Trash2, SquareCheck, Sparkles } from "lucide-react";

import {
  listSubtasksApiV1TasksTaskIdSubtasksGet,
  getListSubtasksApiV1TasksTaskIdSubtasksGetQueryKey,
  createSubtaskApiV1TasksTaskIdSubtasksPost,
  createSubtasksBatchApiV1TasksTaskIdSubtasksBatchPost,
  reorderSubtasksApiV1TasksTaskIdSubtasksOrderPut,
  generateTaskSubtasksApiV1TasksTaskIdAiSubtasksPost,
} from "@/api/generated/tasks/tasks";
import {
  updateSubtaskApiV1SubtasksSubtaskIdPatch,
  deleteSubtaskApiV1SubtasksSubtaskIdDelete,
} from "@/api/generated/subtasks/subtasks";
import { invalidateAllTasks, invalidateTask, invalidateTaskSubtasks } from "@/api/query-keys";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import type { TaskSubtask, TaskSubtaskProgress, GenerateSubtasksResponse } from "@/types/api";
import { TaskChecklistProgress } from "@/components/tasks/TaskChecklistProgress";
import { useAIEnabled } from "@/hooks/useAIEnabled";

type TaskChecklistProps = {
  taskId: number;
  projectId?: number | null;
  canEdit: boolean;
};

type UpdatePayload = {
  subtaskId: number;
  data: Partial<Pick<TaskSubtask, "content" | "is_completed">>;
};

export const TaskChecklist = ({ taskId, canEdit }: TaskChecklistProps) => {
  const { t } = useTranslation(["tasks", "common"]);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [newContent, setNewContent] = useState("");
  const [contentDrafts, setContentDrafts] = useState<Record<number, string>>({});
  const [shouldRefocusAddInput, setShouldRefocusAddInput] = useState(false);
  const { isEnabled: aiEnabled } = useAIEnabled();
  const [aiDialogOpen, setAiDialogOpen] = useState(false);
  const [generatedSubtasks, setGeneratedSubtasks] = useState<string[]>([]);
  const [selectedSubtasks, setSelectedSubtasks] = useState<Set<number>>(new Set());

  const subtasksQueryKey = useMemo(
    () => getListSubtasksApiV1TasksTaskIdSubtasksGetQueryKey(taskId),
    [taskId]
  );

  const invalidateRelatedData = useCallback(() => {
    void invalidateTaskSubtasks(taskId);
    void invalidateTask(taskId);
    void invalidateAllTasks();
  }, [taskId]);

  const subtasksQuery = useQuery<TaskSubtask[]>({
    queryKey: subtasksQueryKey,
    queryFn: async () => {
      const response = await (listSubtasksApiV1TasksTaskIdSubtasksGet(
        taskId
      ) as unknown as Promise<{ data: TaskSubtask[] }>);
      return response.data;
    },
  });

  const [localSubtasks, setLocalSubtasks] = useState<TaskSubtask[]>([]);

  useEffect(() => {
    const subtasks = Array.isArray(subtasksQuery.data) ? subtasksQuery.data : [];
    const sorted = subtasks.slice().sort((a, b) => {
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
      const response = await (createSubtaskApiV1TasksTaskIdSubtasksPost(taskId, {
        content,
      }) as unknown as Promise<{ data: TaskSubtask }>);
      return response.data;
    },
    onSuccess: () => {
      setNewContent("");
      invalidateRelatedData();
      toast.success(t("checklist.itemAdded"));
    },
    onError: (error) => {
      toast.error(parseErrorMessage(error, t("checklist.addError")));
    },
  });

  const updateSubtask = useMutation({
    mutationFn: async ({ subtaskId, data }: UpdatePayload) => {
      const response = await (updateSubtaskApiV1SubtasksSubtaskIdPatch(
        subtaskId,
        data
      ) as unknown as Promise<{ data: TaskSubtask }>);
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
      toast.error(parseErrorMessage(error, t("checklist.updateError")));
    },
  });

  const deleteSubtask = useMutation({
    mutationFn: async (subtaskId: number) => {
      await deleteSubtaskApiV1SubtasksSubtaskIdDelete(subtaskId);
    },
    onSuccess: (_response, subtaskId) => {
      setContentDrafts((previous) => {
        const next = { ...previous };
        delete next[subtaskId];
        return next;
      });
      invalidateRelatedData();
      toast.success(t("checklist.itemDeleted"));
    },
    onError: (error) => {
      toast.error(parseErrorMessage(error, t("checklist.deleteError")));
    },
  });

  const reorderSubtasks = useMutation({
    mutationFn: async (items: { id: number; position: number }[]) => {
      const response = await (reorderSubtasksApiV1TasksTaskIdSubtasksOrderPut(taskId, {
        items,
      }) as unknown as Promise<{ data: TaskSubtask[] }>);
      return response.data;
    },
    onSuccess: () => {
      invalidateRelatedData();
    },
    onError: (error) => {
      toast.error(parseErrorMessage(error, t("checklist.reorderError")));
    },
  });

  const generateSubtasksMutation = useMutation({
    mutationFn: async () => {
      const response = await (generateTaskSubtasksApiV1TasksTaskIdAiSubtasksPost(
        taskId
      ) as unknown as Promise<{ data: GenerateSubtasksResponse }>);
      return response.data;
    },
    onSuccess: (data) => {
      setGeneratedSubtasks(data.subtasks);
      setSelectedSubtasks(new Set(data.subtasks.map((_, index) => index)));
      setAiDialogOpen(true);
    },
    onError: (error) => {
      toast.error(parseErrorMessage(error, t("checklist.generateError")));
    },
  });

  const handleAddSelectedSubtasks = async () => {
    const subtasksToAdd = generatedSubtasks.filter((_, index) => selectedSubtasks.has(index));
    if (subtasksToAdd.length === 0) {
      setAiDialogOpen(false);
      return;
    }

    try {
      await createSubtasksBatchApiV1TasksTaskIdSubtasksBatchPost(taskId, {
        contents: subtasksToAdd,
      });
      invalidateRelatedData();
      toast.success(t("checklist.batchAdded", { count: subtasksToAdd.length }));
      setAiDialogOpen(false);
      setGeneratedSubtasks([]);
      setSelectedSubtasks(new Set());
    } catch (error) {
      toast.error(parseErrorMessage(error, t("checklist.batchAddError")));
    }
  };

  const toggleSubtaskSelection = (index: number) => {
    setSelectedSubtasks((prev) => {
      const next = new Set(prev);
      if (next.has(index)) {
        next.delete(index);
      } else {
        next.add(index);
      }
      return next;
    });
  };

  const handleAdd = () => {
    if (!canEdit || createSubtask.isPending) {
      return;
    }
    const trimmed = newContent.trim();
    if (!trimmed) {
      return;
    }
    setShouldRefocusAddInput(true);
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
      toast.error(t("checklist.contentEmpty"));
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

  useEffect(() => {
    if (shouldRefocusAddInput && !createSubtask.isPending) {
      inputRef.current?.focus();
      setShouldRefocusAddInput(false);
    }
  }, [shouldRefocusAddInput, createSubtask.isPending]);

  return (
    <Card className="shadow-sm">
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle className="flex items-center gap-2">
            <SquareCheck className="text-muted-foreground h-4 w-4" aria-hidden="true" />
            {t("checklist.title")}
          </CardTitle>
          {canEdit && aiEnabled ? (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => generateSubtasksMutation.mutate()}
              disabled={generateSubtasksMutation.isPending}
            >
              {generateSubtasksMutation.isPending ? (
                <Loader2 className="h-3 w-3 animate-spin" />
              ) : (
                <Sparkles className="h-3 w-3" />
              )}
              {t("checklist.aiGenerate")}
            </Button>
          ) : null}
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {subtasksQuery.isLoading ? (
          <p className="text-muted-foreground inline-flex items-center gap-2 text-sm">
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
            {t("checklist.loading")}
          </p>
        ) : subtasksQuery.isError ? (
          <p className="text-destructive text-sm">{t("checklist.loadError")}</p>
        ) : localSubtasks.length === 0 ? (
          <p className="text-muted-foreground text-sm">
            {t("checklist.empty")} {canEdit ? t("checklist.emptyCanEdit") : ""}
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
            placeholder={
              canEdit ? t("checklist.addPlaceholder") : t("checklist.readOnlyPlaceholder")
            }
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
            {t("checklist.addButton")}
          </Button>
        </div>
        {!canEdit ? (
          <p className="text-muted-foreground text-xs">{t("checklist.readOnlyMessage")}</p>
        ) : null}
      </CardContent>

      <Dialog open={aiDialogOpen} onOpenChange={setAiDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t("checklist.aiDialogTitle")}</DialogTitle>
            <DialogDescription>{t("checklist.aiDialogDescription")}</DialogDescription>
          </DialogHeader>
          <div className="space-y-2 py-4">
            {generatedSubtasks.map((subtask, index) => (
              <div key={index} className="flex items-center gap-3 rounded-md border p-3">
                <Checkbox
                  id={`generated-subtask-${index}`}
                  checked={selectedSubtasks.has(index)}
                  onCheckedChange={() => toggleSubtaskSelection(index)}
                />
                <label
                  htmlFor={`generated-subtask-${index}`}
                  className="flex-1 cursor-pointer text-sm"
                >
                  {subtask}
                </label>
              </div>
            ))}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setAiDialogOpen(false)}>
              {t("common:cancel")}
            </Button>
            <Button onClick={handleAddSelectedSubtasks} disabled={selectedSubtasks.size === 0}>
              {t("checklist.addSelected", { count: selectedSubtasks.size })}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
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
  const { t } = useTranslation("tasks");
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
            aria-label={t("checklist.reorderItem")}
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
          aria-label={
            item.is_completed ? t("checklist.markIncomplete") : t("checklist.markComplete")
          }
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
