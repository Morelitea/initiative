import { FormEvent, useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery } from "@tanstack/react-query";
import { toast } from "sonner";

import { apiClient } from "@/api/client";
import { queryClient } from "@/lib/queryClient";
import { Markdown } from "@/components/Markdown";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { AssigneeSelector } from "@/components/projects/AssigneeSelector";
import { useAuth } from "@/hooks/useAuth";
import { useRoleLabels, getRoleLabel } from "@/hooks/useRoleLabels";
import type {
  Comment,
  Project,
  ProjectTaskStatus,
  Task,
  TaskPriority,
  TaskRecurrence,
  User,
} from "@/types/api";
import { Input } from "@/components/ui/input";
import { DateTimePicker } from "@/components/ui/date-time-picker";
import { TaskRecurrenceSelector } from "@/components/projects/TaskRecurrenceSelector";
import { CommentSection } from "@/components/comments/CommentSection";

const priorityOrder: TaskPriority[] = ["low", "medium", "high", "urgent"];

const toLocalInputValue = (value?: string | null) => {
  if (!value) {
    return "";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "";
  }
  const pad = (segment: number) => segment.toString().padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
};

export const TaskEditPage = () => {
  const { taskId } = useParams();
  const parsedTaskId = Number(taskId);
  const navigate = useNavigate();
  const { user } = useAuth();
  const { data: roleLabels } = useRoleLabels();
  const memberLabel = getRoleLabel("member", roleLabels);

  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [isEditingDescription, setIsEditingDescription] = useState(false);
  const [statusId, setStatusId] = useState<number | null>(null);
  const [priority, setPriority] = useState<TaskPriority>("medium");
  const [assigneeIds, setAssigneeIds] = useState<number[]>([]);
  const [startDate, setStartDate] = useState<string>("");
  const [dueDate, setDueDate] = useState<string>("");
  const [recurrence, setRecurrence] = useState<TaskRecurrence | null>(null);

  const taskQuery = useQuery({
    queryKey: ["task", parsedTaskId],
    enabled: Number.isFinite(parsedTaskId),
    queryFn: async () => {
      const response = await apiClient.get<Task>(`/tasks/${parsedTaskId}`);
      return response.data;
    },
  });

  const usersQuery = useQuery({
    queryKey: ["users"],
    queryFn: async () => {
      const response = await apiClient.get<User[]>("/users/");
      return response.data;
    },
  });

  const projectId = taskQuery.data?.project_id;
  const projectQuery = useQuery({
    queryKey: ["project", projectId],
    enabled: Number.isFinite(projectId),
    queryFn: async () => {
      const response = await apiClient.get<Project>(`/projects/${projectId}`);
      return response.data;
    },
  });

  const taskStatusesQuery = useQuery<ProjectTaskStatus[]>({
    queryKey: ["projects", projectId, "task-statuses"],
    enabled: Number.isFinite(projectId),
    queryFn: async () => {
      const response = await apiClient.get<ProjectTaskStatus[]>(
        `/projects/${projectId}/task-statuses/`
      );
      return response.data;
    },
  });

  const commentsQueryKey = ["comments", "task", parsedTaskId];
  const commentsQuery = useQuery({
    queryKey: commentsQueryKey,
    enabled: Number.isFinite(parsedTaskId),
    queryFn: async () => {
      const response = await apiClient.get<Comment[]>("/comments/", {
        params: { task_id: parsedTaskId },
      });
      return response.data;
    },
  });

  useEffect(() => {
    if (taskQuery.data) {
      const task = taskQuery.data;
      setTitle(task.title);
      setDescription(task.description ?? "");
      setStatusId(task.task_status_id);
      setPriority(task.priority);
      setAssigneeIds(task.assignees?.map((assignee) => assignee.id) ?? []);
      setStartDate(toLocalInputValue(task.start_date));
      setDueDate(toLocalInputValue(task.due_date));
      setRecurrence(task.recurrence ?? null);
    }
  }, [taskQuery.data]);

  const isProjectContextLoading =
    Number.isFinite(projectId) && projectQuery.isLoading && !projectQuery.data;

  const updateTask = useMutation({
    mutationFn: async () => {
      if (!Number.isFinite(statusId)) {
        throw new Error("Task status is required");
      }
      const payload: Record<string, unknown> = {
        title,
        description: description || null,
        task_status_id: statusId,
        priority,
        assignee_ids: assigneeIds,
        start_date: startDate ? new Date(startDate).toISOString() : null,
        due_date: dueDate ? new Date(dueDate).toISOString() : null,
        recurrence,
      };
      const response = await apiClient.patch<Task>(`/tasks/${parsedTaskId}`, payload);
      return response.data;
    },
    onSuccess: (updatedTask) => {
      setTitle(updatedTask.title);
      setDescription(updatedTask.description ?? "");
      setIsEditingDescription(false);
      setStatusId(updatedTask.task_status_id);
      setPriority(updatedTask.priority);
      setAssigneeIds(updatedTask.assignees?.map((assignee) => assignee.id) ?? []);
      setStartDate(toLocalInputValue(updatedTask.start_date));
      setDueDate(toLocalInputValue(updatedTask.due_date));
      setRecurrence(updatedTask.recurrence ?? null);
      toast.success("Task updated");
    },
  });

  const deleteTask = useMutation({
    mutationFn: async () => {
      await apiClient.delete(`/tasks/${parsedTaskId}`);
    },
    onSuccess: () => {
      toast.success("Task deleted");
      void queryClient.invalidateQueries({ queryKey: ["tasks"] });
      void queryClient.invalidateQueries({ queryKey: ["tasks", projectId] });
      navigate(projectLink);
    },
  });

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (isReadOnly) {
      return;
    }
    updateTask.mutate();
  };

  const users = useMemo(() => usersQuery.data ?? [], [usersQuery.data]);
  const project = projectQuery.data;
  const userOptions = useMemo(() => {
    if (!project) {
      return users.map((user) => ({
        id: user.id,
        label: user.full_name ?? user.email,
      }));
    }
    const allowed = new Set<number>();
    allowed.add(project.owner_id);
    project.permissions.forEach((permission) => allowed.add(permission.user_id));
    project.initiative?.members?.forEach((member) => {
      if (member.user) {
        allowed.add(member.user.id);
      }
    });

    return users
      .filter((user) => allowed.has(user.id))
      .map((user) => ({
        id: user.id,
        label: user.full_name ?? user.email,
      }));
  }, [users, project]);

  const task = taskQuery.data;
  const projectLink = `/projects/${task?.project_id}`;
  const initiativeMembership = project?.initiative?.members?.find(
    (member) => member.user.id === user?.id
  );
  const isOwner = project?.owner_id === user?.id;
  const isInitiativePm = initiativeMembership?.role === "project_manager";
  const hasExplicitWrite =
    project?.permissions.some((permission) => permission.user_id === user?.id) ?? false;
  const hasImplicitWrite = Boolean(project?.members_can_write && initiativeMembership);
  const canWriteProject =
    user?.role === "admin" || isOwner || isInitiativePm || hasExplicitWrite || hasImplicitWrite;
  const projectIsArchived = project?.is_archived ?? false;
  const isReadOnly = !canWriteProject || projectIsArchived;
  const readOnlyMessage = !canWriteProject
    ? "You only have read access to this project, so task fields are disabled."
    : projectIsArchived
      ? "This project is archived. Unarchive it from project settings to edit tasks."
      : null;
  const canModerateComments = user?.role === "admin" || isInitiativePm;

  const handleCommentCreated = (comment: Comment) => {
    queryClient.setQueryData<Comment[]>(commentsQueryKey, (previous) => {
      if (!previous) {
        return [comment];
      }
      return [...previous, comment];
    });
  };

  const handleCommentDeleted = (commentId: number) => {
    queryClient.setQueryData<Comment[]>(commentsQueryKey, (previous) => {
      if (!previous) {
        return previous;
      }
      return previous.filter((comment) => comment.id !== commentId);
    });
  };

  useEffect(() => {
    if (isReadOnly) {
      setIsEditingDescription(false);
    }
  }, [isReadOnly]);

  if (!Number.isFinite(parsedTaskId)) {
    return (
      <div className="space-y-4">
        <p className="text-destructive">Invalid task id.</p>
        <Button asChild variant="link" className="px-0">
          <Link to="/">← Back to projects</Link>
        </Button>
      </div>
    );
  }

  if (taskQuery.isLoading || isProjectContextLoading || taskStatusesQuery.isLoading) {
    return <p className="text-muted-foreground text-sm">Loading task…</p>;
  }

  if (taskQuery.isError || taskStatusesQuery.isError || !taskQuery.data) {
    return (
      <div className="space-y-4">
        <p className="text-destructive">Unable to load task.</p>
        <Button asChild variant="link" className="px-0">
          <Link to="/">← Back to projects</Link>
        </Button>
      </div>
    );
  }

  if (Number.isFinite(projectId) && projectQuery.isError) {
    return (
      <div className="space-y-4">
        <p className="text-destructive">Unable to load project context for this task.</p>
        <Button asChild variant="link" className="px-0">
          <Link to="/">← Back to projects</Link>
        </Button>
      </div>
    );
  }

  const taskStatuses = taskStatusesQuery.data ?? [];
  const currentStatus = taskStatuses.find((item) => item.id === statusId) ?? null;
  const statusSelectDisabled = isReadOnly || taskStatuses.length === 0;

  return (
    <div className="space-y-6">
      <Button asChild variant="link" className="px-0">
        <Link to={projectLink}>← Back to project</Link>
      </Button>
      <div className="space-y-3">
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="text-3xl font-semibold tracking-tight">{title || task?.title}</h1>
          <Badge variant="secondary">{currentStatus?.name ?? "Status"}</Badge>
        </div>
        <p className="text-muted-foreground text-sm">Edit every detail of this task.</p>
      </div>

      <div className="flex flex-wrap gap-6">
        <Card className="flex-1 shadow-sm md:min-w-100">
          <CardHeader>
            <CardTitle>Task details</CardTitle>
            <CardDescription>Update the fields below and save your changes.</CardDescription>
          </CardHeader>
          <CardContent>
            {isReadOnly && readOnlyMessage ? (
              <p className="border-border bg-muted/50 text-muted-foreground rounded-md border px-3 py-2 text-sm">
                {readOnlyMessage}
              </p>
            ) : null}
            <form className="space-y-6" onSubmit={handleSubmit}>
              <div className="space-y-2">
                <Label htmlFor="task-title">Title</Label>
                <Input
                  id="task-title"
                  value={title}
                  onChange={(event) => setTitle(event.target.value)}
                  placeholder="Task title"
                  required
                  disabled={isReadOnly}
                />
              </div>

              <div className="space-y-2">
                <div className="flex items-center gap-2">
                  <Label htmlFor="task-description">Description</Label>
                  {!isReadOnly ? (
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      className="h-8 px-2 text-xs"
                      onClick={() => setIsEditingDescription((prev) => !prev)}
                    >
                      {isEditingDescription ? "Preview" : "Edit"}
                    </Button>
                  ) : null}
                </div>
                {isEditingDescription && !isReadOnly ? (
                  <Textarea
                    id="task-description"
                    rows={6}
                    value={description}
                    onChange={(event) => setDescription(event.target.value)}
                    placeholder="Add extra context or acceptance criteria. Markdown supported."
                    disabled={isReadOnly}
                  />
                ) : description ? (
                  <div className="border-border/70 bg-muted/40 rounded-md border border-dashed px-3 py-2">
                    <Markdown content={description} />
                  </div>
                ) : (
                  <p className="text-muted-foreground text-sm italic">
                    {isReadOnly
                      ? "No description yet."
                      : "No description yet. Click edit to add more context."}
                  </p>
                )}
              </div>

              <div className="grid gap-4 md:grid-cols-2">
                <div className="space-y-2">
                  <Label>Status</Label>
                  <Select
                    value={statusId ? String(statusId) : undefined}
                    onValueChange={(value) => {
                      const parsed = Number(value);
                      if (Number.isFinite(parsed)) {
                        setStatusId(parsed);
                      }
                    }}
                    disabled={statusSelectDisabled}
                  >
                    <SelectTrigger disabled={statusSelectDisabled}>
                      <SelectValue placeholder="Select status" />
                    </SelectTrigger>
                    <SelectContent>
                      {taskStatuses.map((value) => (
                        <SelectItem key={value.id} value={String(value.id)}>
                          {value.name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-2">
                  <Label>Priority</Label>
                  <Select
                    value={priority}
                    onValueChange={(value) => setPriority(value as TaskPriority)}
                    disabled={isReadOnly}
                  >
                    <SelectTrigger disabled={isReadOnly}>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {priorityOrder.map((value) => (
                        <SelectItem key={value} value={value}>
                          {value.replace("_", " ")}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              </div>

              <div className="grid gap-4 md:grid-cols-2">
                <div className="space-y-2">
                  <Label>Assignees</Label>
                  <AssigneeSelector
                    selectedIds={assigneeIds}
                    options={userOptions}
                    onChange={setAssigneeIds}
                    disabled={isReadOnly}
                    emptyMessage={`No initiative ${memberLabel} role holders available yet.`}
                  />
                </div>
                <div className="space-y-4">
                  <div className="space-y-2">
                    <Label htmlFor="task-start-date">Start date</Label>
                    <DateTimePicker
                      id="task-start-date"
                      value={startDate}
                      onChange={setStartDate}
                      disabled={isReadOnly}
                      placeholder="Optional"
                      calendarProps={{
                        hidden: {
                          after: new Date(dueDate),
                        },
                      }}
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="task-due-date">Due date</Label>
                    <DateTimePicker
                      id="task-due-date"
                      value={dueDate}
                      onChange={setDueDate}
                      disabled={isReadOnly}
                      placeholder="Optional"
                      calendarProps={{
                        hidden: {
                          before: new Date(startDate),
                        },
                      }}
                    />
                  </div>
                </div>
              </div>
              <TaskRecurrenceSelector
                recurrence={recurrence}
                onChange={setRecurrence}
                disabled={isReadOnly}
                referenceDate={dueDate || startDate || task?.due_date || task?.start_date}
              />

              <div className="flex flex-wrap gap-3">
                <Button type="submit" disabled={updateTask.isPending || isReadOnly}>
                  {updateTask.isPending ? "Saving…" : "Save task"}
                </Button>
                <Button type="button" variant="outline" onClick={() => navigate(projectLink)}>
                  Cancel
                </Button>
                {!isReadOnly ? (
                  <Button
                    type="button"
                    variant="destructive"
                    onClick={() => {
                      if (window.confirm("Delete this task? This cannot be undone.")) {
                        deleteTask.mutate();
                      }
                    }}
                    disabled={deleteTask.isPending}
                  >
                    {deleteTask.isPending ? "Deleting…" : "Delete task"}
                  </Button>
                ) : null}
              </div>
            </form>
          </CardContent>
        </Card>

        <div className="w-full max-w-md space-y-2">
          {commentsQuery.isError ? (
            <p className="text-destructive text-sm">Unable to load comments right now.</p>
          ) : null}
          <CommentSection
            entityType="task"
            entityId={parsedTaskId}
            comments={commentsQuery.data ?? []}
            isLoading={commentsQuery.isLoading}
            onCommentCreated={handleCommentCreated}
            onCommentDeleted={handleCommentDeleted}
            canModerate={canModerateComments}
          />
        </div>
      </div>
    </div>
  );
};
