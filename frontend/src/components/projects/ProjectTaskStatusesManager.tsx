import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import {
  DndContext,
  type DragEndEvent,
  MouseSensor,
  TouchSensor,
  useSensor,
  useSensors,
} from "@dnd-kit/core";
import {
  SortableContext,
  arrayMove,
  verticalListSortingStrategy,
  useSortable,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { Loader2, GripVertical, Trash2, Save } from "lucide-react";
import { toast } from "sonner";

import { apiClient } from "@/api/client";
import { queryClient } from "@/lib/queryClient";
import type { ProjectTaskStatus, TaskStatusCategory } from "@/types/api";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { cn } from "@/lib/utils";

const CATEGORY_OPTIONS: { value: TaskStatusCategory; label: string }[] = [
  { value: "backlog", label: "Backlog" },
  { value: "todo", label: "To Do" },
  { value: "in_progress", label: "In Progress" },
  { value: "done", label: "Done" },
];

const STATUS_QUERY_KEY = (projectId: number) => ["projects", projectId, "task-statuses"];

const sortStatuses = (items: ProjectTaskStatus[]): ProjectTaskStatus[] => {
  return [...items].sort((a, b) => {
    if (a.position === b.position) {
      return a.id - b.id;
    }
    return a.position - b.position;
  });
};

interface ProjectTaskStatusesManagerProps {
  projectId: number;
  canManage: boolean;
}

export const ProjectTaskStatusesManager = ({
  projectId,
  canManage,
}: ProjectTaskStatusesManagerProps) => {
  const getErrorMessage = (error: unknown, fallback: string) => {
    if (error instanceof Error && error.message) {
      return error.message;
    }
    return fallback;
  };
  const [orderedStatuses, setOrderedStatuses] = useState<ProjectTaskStatus[]>([]);
  const [drafts, setDrafts] = useState<
    Record<number, { name: string; category: TaskStatusCategory }>
  >({});
  const [newName, setNewName] = useState("");
  const [newCategory, setNewCategory] = useState<TaskStatusCategory>("todo");
  const [deleteTarget, setDeleteTarget] = useState<ProjectTaskStatus | null>(null);
  const [fallbackId, setFallbackId] = useState<string>("");

  const sensors = useSensors(
    useSensor(MouseSensor, { activationConstraint: { distance: 4 } }),
    useSensor(TouchSensor, {
      activationConstraint: {
        delay: 200,
        tolerance: 8,
      },
    })
  );

  const basePath = `/projects/${projectId}/task-statuses`;

  const statusesQuery = useQuery<ProjectTaskStatus[]>({
    queryKey: STATUS_QUERY_KEY(projectId),
    enabled: Number.isFinite(projectId),
    queryFn: async () => {
      const response = await apiClient.get<ProjectTaskStatus[]>(`${basePath}/`);
      return response.data;
    },
  });

  const reorderStatuses = useMutation({
    mutationFn: async (items: { id: number; position: number }[]) => {
      const response = await apiClient.post<ProjectTaskStatus[]>(`${basePath}/reorder`, { items });
      return response.data;
    },
    onSuccess: (data) => {
      const sorted = sortStatuses(data);
      setOrderedStatuses(sorted);
      queryClient.setQueryData(STATUS_QUERY_KEY(projectId), sorted);
      toast.success("Status order saved");
    },
    onError: (error) => {
      toast.error(getErrorMessage(error, "Unable to reorder statuses"));
    },
  });

  useEffect(() => {
    if (!statusesQuery.data || reorderStatuses.isPending) {
      return;
    }
    const sorted = sortStatuses(statusesQuery.data);
    setOrderedStatuses(sorted);
    const nextDrafts: Record<number, { name: string; category: TaskStatusCategory }> = {};
    sorted.forEach((status) => {
      nextDrafts[status.id] = {
        name: status.name,
        category: status.category,
      };
    });
    setDrafts(nextDrafts);
  }, [statusesQuery.data, reorderStatuses.isPending]);

  const invalidateStatuses = () => {
    void queryClient.invalidateQueries({ queryKey: STATUS_QUERY_KEY(projectId) });
    void queryClient.invalidateQueries({ queryKey: ["tasks", projectId] });
  };

  const createStatus = useMutation({
    mutationFn: async () => {
      const payload = {
        name: newName.trim(),
        category: newCategory,
        is_default: false,
      };
      if (!payload.name) {
        throw new Error("Name is required");
      }
      const response = await apiClient.post<ProjectTaskStatus>(`${basePath}/`, payload);
      return response.data;
    },
    onSuccess: () => {
      setNewName("");
      toast.success("Task status created");
      invalidateStatuses();
    },
    onError: (error) => {
      toast.error(getErrorMessage(error, "Unable to create status"));
    },
  });

  const updateStatus = useMutation({
    mutationFn: async ({ statusId, data }: { statusId: number; data: Record<string, unknown> }) => {
      const response = await apiClient.patch<ProjectTaskStatus>(`${basePath}/${statusId}`, data);
      return response.data;
    },
    onSuccess: () => {
      toast.success("Task status updated");
      invalidateStatuses();
    },
    onError: (error) => {
      toast.error(getErrorMessage(error, "Unable to update status"));
    },
  });

  const deleteStatus = useMutation({
    mutationFn: async ({
      statusId,
      fallbackStatusId,
    }: {
      statusId: number;
      fallbackStatusId: number;
    }) => {
      await apiClient.delete(`${basePath}/${statusId}`, {
        data: { fallback_status_id: fallbackStatusId },
      });
    },
    onSuccess: () => {
      toast.success("Task status deleted");
      setFallbackId("");
      setDeleteTarget(null);
      invalidateStatuses();
    },
    onError: (error) => {
      toast.error(getErrorMessage(error, "Unable to delete status"));
    },
  });

  const defaultStatusId = useMemo(() => {
    return orderedStatuses.find((status) => status.is_default)?.id ?? null;
  }, [orderedStatuses]);

  const handleDragEnd = (event: DragEndEvent) => {
    if (!canManage) {
      return;
    }
    const { active, over } = event;
    if (!over || active.id === over.id) {
      return;
    }
    setOrderedStatuses((prev) => {
      const oldIndex = prev.findIndex((status) => status.id === Number(active.id));
      const newIndex = prev.findIndex((status) => status.id === Number(over.id));
      if (oldIndex === -1 || newIndex === -1) {
        return prev;
      }
      const next = arrayMove(prev, oldIndex, newIndex);
      const payload = next.map((status, index) => ({ id: status.id, position: index }));
      reorderStatuses.mutate(payload);
      return next.map((status, index) => ({ ...status, position: index }));
    });
  };

  const handleFieldChange = (statusId: number, field: "name" | "category", value: string) => {
    setDrafts((prev) => ({
      ...prev,
      [statusId]: {
        name: field === "name" ? value : (prev[statusId]?.name ?? ""),
        category:
          field === "category"
            ? (value as TaskStatusCategory)
            : (prev[statusId]?.category ?? "todo"),
      },
    }));
  };

  const handleSaveAll = () => {
    const updates: Array<{ statusId: number; data: Record<string, unknown> }> = [];

    orderedStatuses.forEach((status) => {
      const draft = drafts[status.id];
      if (!draft) {
        return;
      }
      const payload: Record<string, unknown> = {};
      const trimmedName = draft.name.trim();
      if (trimmedName && trimmedName !== status.name) {
        payload.name = trimmedName;
      }
      if (draft.category && draft.category !== status.category) {
        payload.category = draft.category;
      }
      if (Object.keys(payload).length > 0) {
        updates.push({ statusId: status.id, data: payload });
      }
    });

    if (updates.length === 0) {
      toast.info("No changes to save");
      return;
    }

    // Execute all updates in parallel
    Promise.all(
      updates.map(({ statusId, data }) =>
        apiClient.patch<ProjectTaskStatus>(`${basePath}/${statusId}`, data)
      )
    )
      .then(() => {
        toast.success(`${updates.length} status${updates.length === 1 ? "" : "es"} updated`);
        invalidateStatuses();
      })
      .catch((error) => {
        toast.error(getErrorMessage(error, "Unable to update statuses"));
      });
  };

  const hasChanges = useMemo(() => {
    return orderedStatuses.some((status) => {
      const draft = drafts[status.id];
      if (!draft) {
        return false;
      }
      const trimmedName = draft.name.trim();
      return (
        (trimmedName && trimmedName !== status.name) ||
        (draft.category && draft.category !== status.category)
      );
    });
  }, [orderedStatuses, drafts]);

  const handleDefaultChange = (statusId: number) => {
    if (statusId === defaultStatusId) {
      return;
    }
    updateStatus.mutate({ statusId, data: { is_default: true } });
  };

  const handleDeleteConfirm = () => {
    if (!deleteTarget) {
      return;
    }
    const fallback = Number(fallbackId);
    if (!Number.isFinite(fallback)) {
      toast.error("Select a fallback status");
      return;
    }
    deleteStatus.mutate({ statusId: deleteTarget.id, fallbackStatusId: fallback });
  };

  const fallbackOptions = deleteTarget
    ? orderedStatuses.filter(
        (status) => status.category === deleteTarget.category && status.id !== deleteTarget.id
      )
    : [];

  const isLoading = statusesQuery.isLoading || statusesQuery.isRefetching;
  const statuses = useMemo(() => {
    const source = orderedStatuses.length ? orderedStatuses : (statusesQuery.data ?? []);
    return sortStatuses(source);
  }, [orderedStatuses, statusesQuery.data]);

  return (
    <Card>
      <CardHeader>
        <CardTitle>Task statuses</CardTitle>
        <CardDescription>
          Reorder, rename, or change category for the task columns used by this project.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-6">
        {!canManage ? (
          <p className="text-muted-foreground text-sm">
            Only project managers can modify task statuses. Contact a project manager if you need
            changes.
          </p>
        ) : null}
        <div className="space-y-4">
          <h4 className="text-sm font-semibold">Add status</h4>
          <div className="flex flex-wrap gap-3">
            <Input
              className="max-w-xs"
              placeholder="Status name"
              value={newName}
              onChange={(event) => setNewName(event.target.value)}
              disabled={!canManage || createStatus.isPending}
            />
            <Select
              value={newCategory}
              onValueChange={(value) => setNewCategory(value as TaskStatusCategory)}
              disabled={!canManage || createStatus.isPending}
            >
              <SelectTrigger className="w-48">
                <SelectValue placeholder="Select category" />
              </SelectTrigger>
              <SelectContent>
                {CATEGORY_OPTIONS.map((option) => (
                  <SelectItem key={option.value} value={option.value}>
                    {option.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Button
              onClick={() => createStatus.mutate()}
              disabled={!canManage || createStatus.isPending}
            >
              {createStatus.isPending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
              Add
            </Button>
          </div>
        </div>

        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <h4 className="text-sm font-semibold">Existing statuses</h4>
            <div className="flex items-center gap-2">
              {isLoading ? (
                <Loader2 className="text-muted-foreground h-4 w-4 animate-spin" />
              ) : null}
              {canManage && (
                <Button
                  variant="outline"
                  size="sm"
                  onClick={handleSaveAll}
                  disabled={!hasChanges || updateStatus.isPending}
                >
                  <Save className="mr-2 h-4 w-4" />
                  Save changes
                </Button>
              )}
            </div>
          </div>
          <div className="overflow-x-auto rounded-md border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-10" />
                  <TableHead className="min-w-40">Name</TableHead>
                  <TableHead>Category</TableHead>
                  <TableHead className="w-24 text-center">Default</TableHead>
                  <TableHead className="w-20 text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                <DndContext sensors={sensors} onDragEnd={handleDragEnd}>
                  <SortableContext
                    items={statuses.map((status) => status.id)}
                    strategy={verticalListSortingStrategy}
                  >
                    {statuses.map((status) => (
                      <SortableStatusRow
                        key={status.id}
                        status={status}
                        draft={drafts[status.id]}
                        disabled={!canManage}
                        isDefault={status.id === defaultStatusId}
                        onFieldChange={handleFieldChange}
                        onSetDefault={handleDefaultChange}
                        onDelete={() => {
                          setDeleteTarget(status);
                          setFallbackId("");
                        }}
                      />
                    ))}
                  </SortableContext>
                </DndContext>
                {statuses.length === 0 ? (
                  <TableRow>
                    <TableCell
                      colSpan={5}
                      className="text-muted-foreground py-6 text-center text-sm"
                    >
                      No statuses configured yet.
                    </TableCell>
                  </TableRow>
                ) : null}
              </TableBody>
            </Table>
          </div>
        </div>
      </CardContent>

      <Dialog open={Boolean(deleteTarget)} onOpenChange={(open) => !open && setDeleteTarget(null)}>
        <DialogContent className="bg-card max-h-screen overflow-y-auto">
          <DialogHeader>
            <DialogTitle>Delete status</DialogTitle>
            <DialogDescription>
              Select a fallback status in the same category to move any existing tasks before
              deleting &quot;{deleteTarget?.name}&quot;.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-2">
            <Label htmlFor="fallback-status">Fallback status</Label>
            <Select
              value={fallbackId}
              onValueChange={setFallbackId}
              disabled={fallbackOptions.length === 0}
            >
              <SelectTrigger id="fallback-status">
                <SelectValue
                  placeholder={fallbackOptions.length ? "Choose fallback" : "No fallback available"}
                />
              </SelectTrigger>
              <SelectContent>
                {fallbackOptions.map((option) => (
                  <SelectItem key={option.id} value={String(option.id)}>
                    {option.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setDeleteTarget(null)}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              onClick={handleDeleteConfirm}
              disabled={deleteStatus.isPending || !fallbackOptions.length}
            >
              {deleteStatus.isPending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
              Delete
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Card>
  );
};

interface SortableStatusRowProps {
  status: ProjectTaskStatus;
  draft?: { name: string; category: TaskStatusCategory };
  disabled: boolean;
  isDefault: boolean;
  onFieldChange: (statusId: number, field: "name" | "category", value: string) => void;
  onSetDefault: (statusId: number) => void;
  onDelete: () => void;
}

const SortableStatusRow = ({
  status,
  draft,
  disabled,
  isDefault,
  onFieldChange,
  onSetDefault,
  onDelete,
}: SortableStatusRowProps) => {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: status.id,
    disabled,
  });

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
  };

  return (
    <TableRow ref={setNodeRef} style={style} className={cn(isDragging && "bg-muted/40")}>
      <TableCell>
        <button
          type="button"
          className="text-muted-foreground"
          {...attributes}
          {...listeners}
          disabled={disabled}
          aria-label="Reorder"
        >
          <GripVertical className="h-4 w-4" />
        </button>
      </TableCell>
      <TableCell>
        <Input
          value={draft?.name ?? status.name}
          onChange={(event) => onFieldChange(status.id, "name", event.target.value)}
          disabled={disabled}
        />
      </TableCell>
      <TableCell>
        <Select
          value={draft?.category ?? status.category}
          onValueChange={(value) => onFieldChange(status.id, "category", value)}
          disabled={disabled}
        >
          <SelectTrigger>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {CATEGORY_OPTIONS.map((option) => (
              <SelectItem key={option.value} value={option.value}>
                {option.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </TableCell>
      <TableCell className="text-center">
        <Checkbox
          checked={isDefault}
          onCheckedChange={(checked) => {
            if (checked) {
              onSetDefault(status.id);
            }
          }}
          aria-label="Set as default"
          disabled={disabled || isDefault}
        />
      </TableCell>
      <TableCell className="text-right">
        <Button
          variant="ghost"
          size="sm"
          className="text-destructive hover:text-destructive"
          onClick={onDelete}
          disabled={disabled}
        >
          <Trash2 className="mr-1 h-4 w-4" />
        </Button>
      </TableCell>
    </TableRow>
  );
};
