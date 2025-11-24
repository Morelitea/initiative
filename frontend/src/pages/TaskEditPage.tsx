import { FormEvent, useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery } from "@tanstack/react-query";

import { apiClient } from "../api/client";
import { queryClient } from "../lib/queryClient";
import { Badge } from "../components/ui/badge";
import { Button } from "../components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../components/ui/card";
import { Label } from "../components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "../components/ui/select";
import { Textarea } from "../components/ui/textarea";
import { AssigneeSelector } from "../components/projects/AssigneeSelector";
import { toast } from "sonner";
import { useAuth } from "../hooks/useAuth";
import type { Project, ProjectRole, Task, TaskPriority, TaskRecurrence, TaskStatus, User } from "../types/api";
import { Input } from "../components/ui/input";
import { DateTimePicker } from "../components/ui/date-time-picker";
import { TaskRecurrenceSelector } from "../components/projects/TaskRecurrenceSelector";

const taskStatusOrder: TaskStatus[] = ["backlog", "in_progress", "blocked", "done"];
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

  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [status, setStatus] = useState<TaskStatus>("backlog");
  const [priority, setPriority] = useState<TaskPriority>("medium");
  const [assigneeIds, setAssigneeIds] = useState<number[]>([]);
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

  useEffect(() => {
    if (taskQuery.data) {
      const task = taskQuery.data;
      setTitle(task.title);
      setDescription(task.description ?? "");
      setStatus(task.status);
      setPriority(task.priority);
      setAssigneeIds(task.assignees?.map((assignee) => assignee.id) ?? []);
      setDueDate(toLocalInputValue(task.due_date));
      setRecurrence(task.recurrence ?? null);
    }
  }, [taskQuery.data]);

  const isProjectContextLoading =
    Number.isFinite(projectId) && projectQuery.isLoading && !projectQuery.data;

  const updateTask = useMutation({
    mutationFn: async () => {
      const payload: Record<string, unknown> = {
        title,
        description: description || null,
        status,
        priority,
        assignee_ids: assigneeIds,
        due_date: dueDate ? new Date(dueDate).toISOString() : null,
        recurrence,
      };
      const response = await apiClient.patch<Task>(`/tasks/${parsedTaskId}`, payload);
      return response.data;
    },
    onSuccess: (updatedTask) => {
      setTitle(updatedTask.title);
      setDescription(updatedTask.description ?? "");
      setStatus(updatedTask.status);
      setPriority(updatedTask.priority);
      setAssigneeIds(updatedTask.assignees?.map((assignee) => assignee.id) ?? []);
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
    project.members.forEach((member) => allowed.add(member.user_id));
    project.initiative?.members?.forEach((member) => allowed.add(member.id));

    return users
      .filter((user) => allowed.has(user.id))
      .map((user) => ({
        id: user.id,
        label: user.full_name ?? user.email,
      }));
  }, [users, project]);

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

  if (taskQuery.isLoading || isProjectContextLoading) {
    return <p className="text-sm text-muted-foreground">Loading task…</p>;
  }

  if (taskQuery.isError || !taskQuery.data) {
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

  const task = taskQuery.data;
  const projectLink = `/projects/${task.project_id}`;
  const membershipRole = project?.members.find((member) => member.user_id === user?.id)?.role;
  const userProjectRole = user?.role as ProjectRole | undefined;
  const writeRoles = project?.write_roles ?? [];
  const canWriteProject =
    user?.role === "admin" ||
    (membershipRole ? writeRoles.includes(membershipRole) : false) ||
    (userProjectRole ? writeRoles.includes(userProjectRole) : false);
  const projectIsArchived = project?.is_archived ?? false;
  const isReadOnly = !canWriteProject || projectIsArchived;
  const readOnlyMessage = !canWriteProject
    ? "You only have read access to this project, so task fields are disabled."
    : projectIsArchived
      ? "This project is archived. Unarchive it from project settings to edit tasks."
      : null;

  return (
    <div className="space-y-6">
      <Button asChild variant="link" className="px-0">
        <Link to={projectLink}>← Back to project</Link>
      </Button>
      <div className="space-y-3">
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="text-3xl font-semibold tracking-tight">{title || task.title}</h1>
          <Badge variant="secondary" className="capitalize">
            {status.replace("_", " ")}
          </Badge>
        </div>
        <p className="text-sm text-muted-foreground">Edit every detail of this task.</p>
      </div>

      <Card className="shadow-sm">
        <CardHeader>
          <CardTitle>Task details</CardTitle>
          <CardDescription>Update the fields below and save your changes.</CardDescription>
        </CardHeader>
        <CardContent>
          {isReadOnly && readOnlyMessage ? (
            <p className="rounded-md border border-border bg-muted/50 px-3 py-2 text-sm text-muted-foreground">
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
              <Label htmlFor="task-description">Description</Label>
              <Textarea
                id="task-description"
                rows={4}
                value={description}
                onChange={(event) => setDescription(event.target.value)}
                placeholder="Add extra context or acceptance criteria."
                disabled={isReadOnly}
              />
            </div>

            <div className="grid gap-4 md:grid-cols-2">
              <div className="space-y-2">
                <Label>Status</Label>
                <Select
                  value={status}
                  onValueChange={(value) => setStatus(value as TaskStatus)}
                  disabled={isReadOnly}
                >
                  <SelectTrigger disabled={isReadOnly}>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {taskStatusOrder.map((value) => (
                      <SelectItem key={value} value={value}>
                        {value.replace("_", " ")}
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
                  emptyMessage="No initiative members available yet."
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
                />
              </div>
            </div>
            <TaskRecurrenceSelector
              recurrence={recurrence}
              onChange={setRecurrence}
              disabled={isReadOnly}
              referenceDate={dueDate || task.due_date}
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
    </div>
  );
};
