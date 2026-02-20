import { FormEvent, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useParams, useRouter } from "@tanstack/react-router";
import { toast } from "sonner";

import { queryClient } from "@/lib/queryClient";
import { getReadTaskApiV1TasksTaskIdGetQueryKey } from "@/api/generated/tasks/tasks";
import { getListCommentsApiV1CommentsGetQueryKey } from "@/api/generated/comments/comments";
import { useComments } from "@/hooks/useComments";
import { useProject, useProjectTaskStatuses, useWritableProjects } from "@/hooks/useProjects";
import {
  useTask,
  useUpdateTask,
  useDeleteTask,
  useDuplicateTask,
  useMoveTask,
  useGenerateTaskDescription,
} from "@/hooks/useTasks";
import { useUsers } from "@/hooks/useUsers";
import { invalidateProject, invalidateProjectTaskStatuses } from "@/api/query-keys";
import { Markdown } from "@/components/Markdown";
import { Badge } from "@/components/ui/badge";
import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from "@/components/ui/breadcrumb";
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
import { useGuilds } from "@/hooks/useGuilds";
import { useGuildPath } from "@/lib/guildUrl";
import { useRoleLabels, getRoleLabel } from "@/hooks/useRoleLabels";
import type {
  CommentRead,
  TagSummary,
  TaskListRead,
  TaskListReadRecurrenceStrategy,
  TaskPriority,
  TaskRecurrenceOutput,
} from "@/api/generated/initiativeAPI.schemas";
import { useAIEnabled } from "@/hooks/useAIEnabled";
import { Input } from "@/components/ui/input";
import { DateTimePicker } from "@/components/ui/date-time-picker";
import { TaskRecurrenceSelector } from "@/components/projects/TaskRecurrenceSelector";
import { CommentSection } from "@/components/comments/CommentSection";
import { MoveTaskDialog } from "@/components/tasks/MoveTaskDialog";
import { TaskChecklist } from "@/components/tasks/TaskChecklist";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { TagPicker } from "@/components/tags";
import { useSetTaskTags } from "@/hooks/useTags";
import {
  Archive,
  ArchiveRestore,
  Save,
  X,
  FolderInput,
  Copy,
  Trash2,
  Sparkles,
  Loader2,
} from "lucide-react";

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

type MoveTaskVariables = {
  targetProjectId: number;
  targetProjectName?: string;
  previousProjectId: number | null;
};

export const TaskEditPage = () => {
  const { taskId } = useParams({ strict: false }) as { taskId: string };
  const parsedTaskId = Number(taskId);
  const router = useRouter();
  useAuth();
  useGuilds();
  const { t } = useTranslation(["tasks", "common"]);
  const gp = useGuildPath();
  const { data: roleLabels } = useRoleLabels();
  const memberLabel = getRoleLabel("member", roleLabels);
  const { isEnabled: aiEnabled } = useAIEnabled();

  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [isEditingDescription, setIsEditingDescription] = useState(false);
  const [statusId, setStatusId] = useState<number | null>(null);
  const [priority, setPriority] = useState<TaskPriority>("medium");
  const [assigneeIds, setAssigneeIds] = useState<number[]>([]);
  const [startDate, setStartDate] = useState<string>("");
  const [dueDate, setDueDate] = useState<string>("");
  const [recurrence, setRecurrence] = useState<TaskRecurrenceOutput | null>(null);
  const [recurrenceStrategy, setRecurrenceStrategy] =
    useState<TaskListReadRecurrenceStrategy>("fixed");
  const [tags, setTags] = useState<TagSummary[]>([]);
  const [isMoveDialogOpen, setIsMoveDialogOpen] = useState(false);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [moveContext, setMoveContext] = useState<MoveTaskVariables | null>(null);

  const taskQuery = useTask(parsedTaskId);

  const usersQuery = useUsers();

  const projectId = taskQuery.data?.project_id;
  const projectQuery = useProject(projectId ?? null);

  const taskStatusesQuery = useProjectTaskStatuses(projectId ?? null);

  const commentsQueryParams = { task_id: parsedTaskId };
  const commentsQueryKey = getListCommentsApiV1CommentsGetQueryKey(commentsQueryParams);
  const commentsQuery = useComments(commentsQueryParams, {
    enabled: Number.isFinite(parsedTaskId),
  });

  const setTaskTagsMutation = useSetTaskTags();

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
      setRecurrenceStrategy(task.recurrence_strategy ?? "fixed");
      setTags(task.tags ?? []);
    }
  }, [taskQuery.data]);

  const isProjectContextLoading =
    Number.isFinite(projectId) && projectQuery.isLoading && !projectQuery.data;

  const updateTask = useUpdateTask({
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
      setRecurrenceStrategy(updatedTask.recurrence_strategy ?? "fixed");
      toast.success(t("edit.taskUpdated"));
    },
  });

  const duplicateTask = useDuplicateTask({
    onSuccess: (newTask) => {
      toast.success(t("edit.taskDuplicated"));
      router.navigate({ to: gp(`/tasks/${newTask.id}`) });
    },
  });

  const deleteTask = useDeleteTask({
    onSuccess: () => {
      toast.success(t("edit.taskDeleted"));
      router.navigate({ to: gp(`/projects/${projectId}`) });
    },
  });

  const moveTask = useMoveTask({
    onSuccess: (updatedTask) => {
      queryClient.setQueryData<TaskListRead>(
        getReadTaskApiV1TasksTaskIdGetQueryKey(parsedTaskId),
        updatedTask
      );
      const previousProjectId = moveContext?.previousProjectId;
      if (typeof previousProjectId === "number") {
        void invalidateProjectTaskStatuses(previousProjectId);
        void invalidateProject(previousProjectId);
      }
      if (typeof moveContext?.targetProjectId === "number") {
        void invalidateProjectTaskStatuses(moveContext.targetProjectId);
        void invalidateProject(moveContext.targetProjectId);
      }
      setIsMoveDialogOpen(false);
      toast.success(
        t("edit.moveSuccess", {
          projectName: moveContext?.targetProjectName ?? "the selected project",
        })
      );
      setMoveContext(null);
    },
  });

  const toggleArchive = useUpdateTask({
    onSuccess: (updatedTask) => {
      queryClient.setQueryData<TaskListRead>(
        getReadTaskApiV1TasksTaskIdGetQueryKey(parsedTaskId),
        updatedTask
      );
      toast.success(updatedTask.is_archived ? t("edit.taskArchived") : t("edit.taskUnarchived"));
    },
  });

  const generateDescription = useGenerateTaskDescription({
    onSuccess: (data) => {
      setDescription(data.description);
      setIsEditingDescription(true);
      toast.success(t("edit.descriptionGenerated"));
    },
  });

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (isReadOnly) {
      return;
    }
    if (!Number.isFinite(statusId)) {
      toast.error(t("edit.taskStatusRequired"));
      return;
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
      recurrence_strategy: recurrence ? recurrenceStrategy : "fixed",
    };
    updateTask.mutate({ taskId: parsedTaskId, data: payload as never });
  };

  const handleMoveTask = (targetProjectId: number) => {
    if (moveTask.isPending || !task) {
      return;
    }
    const targetProject = writableProjects.find((project) => project.id === targetProjectId);
    const context: MoveTaskVariables = {
      targetProjectId,
      targetProjectName: targetProject?.name,
      previousProjectId: task.project_id ?? null,
    };
    setMoveContext(context);
    moveTask.mutate({
      taskId: parsedTaskId,
      targetProjectId,
    });
  };

  const users = useMemo(() => usersQuery.data ?? [], [usersQuery.data]);
  const project = projectQuery.data;
  // Pure DAC: only users with write access (owner or write level) can be assigned tasks
  // Includes both explicit user permissions and role-based permissions
  const userOptions = useMemo(() => {
    if (!project) {
      return users.map((user) => ({
        id: user.id,
        label: user.full_name ?? user.email,
      }));
    }
    const allowed = new Set<number>();
    // Explicit user permissions
    project.permissions?.forEach((permission) => {
      if (permission.level === "owner" || permission.level === "write") {
        allowed.add(permission.user_id);
      }
    });

    // Role-based permissions: find roles with write access,
    // then include initiative members with those roles
    const writeRoleIds = new Set(
      project.role_permissions
        ?.filter((rp) => rp.level === "write")
        .map((rp) => rp.initiative_role_id) ?? []
    );
    if (writeRoleIds.size > 0) {
      project.initiative?.members?.forEach((member) => {
        if (member.role_id && writeRoleIds.has(member.role_id)) {
          allowed.add(member.user.id);
        }
      });
    }

    return users
      .filter((user) => allowed.has(user.id))
      .map((user) => ({
        id: user.id,
        label: user.full_name ?? user.email,
      }));
  }, [users, project]);

  const task = taskQuery.data;
  // Pure DAC: permissions inherited from project
  const myLevel = project?.my_permission_level;
  const hasWritePermission = myLevel === "owner" || myLevel === "write";
  const canWriteProject = hasWritePermission;
  const projectIsArchived = project?.is_archived ?? false;
  const isReadOnly = !canWriteProject || projectIsArchived;
  const readOnlyMessage = !canWriteProject
    ? t("edit.readOnlyNoAccess")
    : projectIsArchived
      ? t("edit.readOnlyArchived")
      : null;
  // Pure DAC: comment moderation requires write permission on project
  const canModerateComments = hasWritePermission;

  const writableProjectsQuery = useWritableProjects({
    enabled: Boolean(canWriteProject && !projectIsArchived),
  });
  const writableProjects = writableProjectsQuery.data ?? [];

  const handleCommentCreated = (comment: CommentRead) => {
    queryClient.setQueryData<CommentRead[]>(commentsQueryKey, (previous) => {
      if (!previous) {
        return [comment];
      }
      return [...previous, comment];
    });
  };

  const handleCommentDeleted = (commentId: number) => {
    queryClient.setQueryData<CommentRead[]>(commentsQueryKey, (previous) => {
      if (!previous) {
        return previous;
      }
      return previous.filter((comment) => comment.id !== commentId);
    });
  };

  const handleCommentUpdated = (updatedComment: CommentRead) => {
    queryClient.setQueryData<CommentRead[]>(commentsQueryKey, (previous) => {
      if (!previous) {
        return previous;
      }
      return previous.map((comment) =>
        comment.id === updatedComment.id ? updatedComment : comment
      );
    });
  };

  useEffect(() => {
    if (isReadOnly) {
      setIsEditingDescription(false);
    }
  }, [isReadOnly]);

  const handleTagsChange = (newTags: TagSummary[]) => {
    setTags(newTags);
    // Save tags immediately via separate endpoint
    setTaskTagsMutation.mutate({
      taskId: parsedTaskId,
      tagIds: newTags.map((t) => t.id),
    });
  };

  const handleBackClick = () => {
    router.history.back();
  };

  if (!Number.isFinite(parsedTaskId)) {
    return (
      <div className="space-y-4">
        <p className="text-destructive">{t("edit.invalidTaskId")}</p>
        <Button variant="link" className="px-0" onClick={handleBackClick}>
          {t("edit.back")}
        </Button>
      </div>
    );
  }

  if (taskQuery.isLoading || isProjectContextLoading || taskStatusesQuery.isLoading) {
    return <p className="text-muted-foreground text-sm">{t("edit.loadingTask")}</p>;
  }

  if (taskQuery.isError || taskStatusesQuery.isError || !taskQuery.data) {
    return (
      <div className="space-y-4">
        <p className="text-destructive">{t("edit.loadError")}</p>
        <Button variant="link" className="px-0" onClick={handleBackClick}>
          {t("edit.back")}
        </Button>
      </div>
    );
  }

  if (Number.isFinite(projectId) && projectQuery.isError) {
    return (
      <div className="space-y-4">
        <p className="text-destructive">{t("edit.loadProjectError")}</p>
        <Button variant="link" className="px-0" onClick={handleBackClick}>
          {t("edit.back")}
        </Button>
      </div>
    );
  }

  const taskStatuses = taskStatusesQuery.data ?? [];
  const currentStatus = taskStatuses.find((item) => item.id === statusId) ?? null;
  const statusSelectDisabled = isReadOnly || taskStatuses.length === 0;

  return (
    <div className="space-y-6">
      <Breadcrumb>
        <BreadcrumbList>
          {project?.initiative && (
            <>
              <BreadcrumbItem>
                <BreadcrumbLink asChild>
                  <Link to={gp(`/initiatives/${project.initiative.id}`)}>
                    {project.initiative.name}
                  </Link>
                </BreadcrumbLink>
              </BreadcrumbItem>
              <BreadcrumbSeparator />
            </>
          )}
          {project && (
            <>
              <BreadcrumbItem>
                <BreadcrumbLink asChild>
                  <Link to={gp(`/projects/${project.id}`)}>{project.name}</Link>
                </BreadcrumbLink>
              </BreadcrumbItem>
              <BreadcrumbSeparator />
            </>
          )}
          <BreadcrumbItem>
            <BreadcrumbPage>{title || task?.title}</BreadcrumbPage>
          </BreadcrumbItem>
        </BreadcrumbList>
      </Breadcrumb>
      <div className="space-y-3">
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="text-3xl font-semibold tracking-tight">{title || task?.title}</h1>
          <Badge variant="secondary">{currentStatus?.name ?? t("edit.statusBadge")}</Badge>
        </div>
        <p className="text-muted-foreground text-sm">{t("edit.subtitle")}</p>
      </div>

      <div className="flex flex-wrap gap-6">
        <Card className="flex-1 shadow-sm sm:min-w-100">
          <CardHeader>
            <CardTitle>{t("edit.detailsTitle")}</CardTitle>
            <CardDescription>{t("edit.detailsDescription")}</CardDescription>
          </CardHeader>
          <CardContent>
            {isReadOnly && readOnlyMessage ? (
              <p className="border-border bg-muted/50 text-muted-foreground rounded-md border px-3 py-2 text-sm">
                {readOnlyMessage}
              </p>
            ) : null}
            <form className="space-y-6" onSubmit={handleSubmit}>
              <div className="space-y-2">
                <Label htmlFor="task-title">{t("edit.titleLabel")}</Label>
                <Input
                  id="task-title"
                  value={title}
                  onChange={(event) => setTitle(event.target.value)}
                  placeholder={t("edit.titlePlaceholder")}
                  required
                  disabled={isReadOnly}
                />
              </div>

              <div className="space-y-2">
                <div className="flex items-center gap-2">
                  <Label htmlFor="task-description">{t("edit.descriptionLabel")}</Label>
                  {!isReadOnly ? (
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      className="h-8 px-2 text-xs"
                      onClick={() => setIsEditingDescription((prev) => !prev)}
                    >
                      {isEditingDescription ? t("edit.preview") : t("common:edit")}
                    </Button>
                  ) : null}
                  {!isReadOnly && aiEnabled ? (
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      className="h-8 px-2 text-xs"
                      onClick={() => generateDescription.mutate(parsedTaskId)}
                      disabled={generateDescription.isPending}
                    >
                      {generateDescription.isPending ? (
                        <Loader2 className="h-3 w-3 animate-spin" />
                      ) : (
                        <Sparkles className="h-3 w-3" />
                      )}
                      {t("edit.aiGenerate")}
                    </Button>
                  ) : null}
                </div>
                {isEditingDescription && !isReadOnly ? (
                  <Textarea
                    id="task-description"
                    rows={6}
                    value={description}
                    onChange={(event) => setDescription(event.target.value)}
                    placeholder={t("edit.descriptionPlaceholder")}
                    disabled={isReadOnly}
                  />
                ) : description ? (
                  <div className="border-border/70 bg-muted/40 rounded-md border border-dashed px-3 py-2">
                    <Markdown content={description} />
                  </div>
                ) : (
                  <p className="text-muted-foreground text-sm italic">
                    {isReadOnly ? t("edit.noDescriptionReadOnly") : t("edit.noDescription")}
                  </p>
                )}
              </div>

              <div className="grid gap-4 md:grid-cols-2">
                <div className="space-y-2">
                  <Label>{t("edit.statusLabel")}</Label>
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
                      <SelectValue placeholder={t("edit.selectStatus")} />
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
                  <Label>{t("edit.priorityLabel")}</Label>
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
                          {t(`priority.${value}` as never)}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              </div>

              <div className="grid gap-4 md:grid-cols-2">
                <div className="space-y-2">
                  <Label htmlFor="task-start-date">{t("edit.startDateLabel")}</Label>
                  <DateTimePicker
                    id="task-start-date"
                    value={startDate}
                    onChange={setStartDate}
                    disabled={isReadOnly}
                    placeholder={t("common:optional")}
                    calendarProps={{
                      hidden: {
                        after: new Date(dueDate),
                      },
                    }}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="task-due-date">{t("edit.dueDateLabel")}</Label>
                  <DateTimePicker
                    id="task-due-date"
                    value={dueDate}
                    onChange={setDueDate}
                    disabled={isReadOnly}
                    placeholder={t("common:optional")}
                    calendarProps={{
                      hidden: {
                        before: new Date(startDate),
                      },
                    }}
                  />
                </div>
              </div>

              <div className="grid gap-4 md:grid-cols-2">
                <div className="space-y-2">
                  <Label>{t("edit.assigneesLabel")}</Label>
                  <AssigneeSelector
                    selectedIds={assigneeIds}
                    options={userOptions}
                    onChange={setAssigneeIds}
                    disabled={isReadOnly}
                    emptyMessage={t("edit.assigneesEmptyMessage", { memberLabel })}
                  />
                </div>
                <div className="space-y-2">
                  <Label>{t("edit.tagsLabel")}</Label>
                  <TagPicker
                    selectedTags={tags}
                    onChange={handleTagsChange}
                    disabled={isReadOnly}
                    placeholder={t("edit.tagsPlaceholder")}
                  />
                </div>
              </div>

              <TaskRecurrenceSelector
                recurrence={recurrence}
                onChange={setRecurrence}
                strategy={recurrenceStrategy}
                onStrategyChange={setRecurrenceStrategy}
                disabled={isReadOnly}
                referenceDate={dueDate || startDate || task?.due_date || task?.start_date}
              />

              <div className="flex flex-wrap gap-3">
                <Button type="submit" disabled={updateTask.isPending || isReadOnly}>
                  <Save className="h-4 w-4" />
                  {updateTask.isPending ? t("edit.saving") : t("edit.saveTask")}
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => router.navigate({ to: gp(`/projects/${projectId}`) })}
                >
                  <X className="h-4 w-4" />
                  {t("common:cancel")}
                </Button>
                {!isReadOnly ? (
                  <>
                    <MoveTaskDialog
                      trigger={
                        <Button type="button" variant="secondary" disabled={moveTask.isPending}>
                          <FolderInput className="h-4 w-4" />
                          {t("edit.moveToProject")}
                        </Button>
                      }
                      open={isMoveDialogOpen}
                      onOpenChange={setIsMoveDialogOpen}
                      projects={writableProjects}
                      currentProjectId={task?.project_id ?? null}
                      isLoading={writableProjectsQuery.isLoading}
                      hasError={Boolean(writableProjectsQuery.isError)}
                      isSaving={moveTask.isPending}
                      onConfirm={handleMoveTask}
                    />
                    <Button
                      type="button"
                      variant="secondary"
                      onClick={() => {
                        duplicateTask.mutate(parsedTaskId);
                      }}
                      disabled={duplicateTask.isPending}
                    >
                      <Copy className="h-4 w-4" />
                      {duplicateTask.isPending ? t("edit.duplicating") : t("edit.duplicateTask")}
                    </Button>
                    <Button
                      type="button"
                      variant="secondary"
                      onClick={() =>
                        toggleArchive.mutate({
                          taskId: parsedTaskId,
                          data: { is_archived: !task?.is_archived } as never,
                        })
                      }
                      disabled={toggleArchive.isPending}
                    >
                      {task?.is_archived ? (
                        <>
                          <ArchiveRestore className="h-4 w-4" />
                          {toggleArchive.isPending ? t("edit.unarchiving") : t("edit.unarchive")}
                        </>
                      ) : (
                        <>
                          <Archive className="h-4 w-4" />
                          {toggleArchive.isPending ? t("edit.archiving") : t("edit.archive")}
                        </>
                      )}
                    </Button>
                    <Button
                      type="button"
                      variant="destructive"
                      onClick={() => setShowDeleteConfirm(true)}
                      disabled={deleteTask.isPending}
                    >
                      <Trash2 className="h-4 w-4" />
                      {deleteTask.isPending ? t("edit.deleting") : t("edit.deleteTask")}
                    </Button>
                  </>
                ) : null}
              </div>
            </form>
          </CardContent>
        </Card>

        <div className="flex-1 space-y-4 sm:min-w-100">
          <TaskChecklist
            taskId={parsedTaskId}
            projectId={task?.project_id ?? null}
            canEdit={!isReadOnly}
          />
          {commentsQuery.isError ? (
            <p className="text-destructive text-sm">{t("edit.commentsError")}</p>
          ) : null}
          <CommentSection
            entityType="task"
            entityId={parsedTaskId}
            comments={commentsQuery.data ?? []}
            isLoading={commentsQuery.isLoading}
            onCommentCreated={handleCommentCreated}
            onCommentDeleted={handleCommentDeleted}
            onCommentUpdated={handleCommentUpdated}
            canModerate={canModerateComments}
            initiativeId={projectQuery.data?.initiative_id ?? 0}
          />
        </div>
      </div>

      <ConfirmDialog
        open={showDeleteConfirm}
        onOpenChange={setShowDeleteConfirm}
        title={t("edit.deleteTitle")}
        description={t("edit.deleteDescription")}
        confirmLabel={t("common:delete")}
        onConfirm={() => {
          deleteTask.mutate(parsedTaskId);
          setShowDeleteConfirm(false);
        }}
        isLoading={deleteTask.isPending}
        destructive
      />
    </div>
  );
};
