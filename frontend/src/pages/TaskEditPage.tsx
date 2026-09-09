import { useBlocker, useParams, useRouter } from "@tanstack/react-router";
import { format } from "date-fns";
import {
  AlertCircle,
  Archive,
  ArchiveRestore,
  Copy,
  FolderInput,
  Loader2,
  MoreHorizontal,
  Save,
  SearchX,
  ShieldAlert,
  Sparkles,
  Trash2,
  X,
} from "lucide-react";
import { type FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { getListCommentsApiV1GGuildIdCommentsGetQueryKey } from "@/api/generated/comments/comments";
import type { CommentRead, PropertySummary, TaskRead } from "@/api/generated/initiativeAPI.schemas";
import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { getReadTaskApiV1GGuildIdTasksTaskIdGetQueryKey } from "@/api/generated/tasks/tasks";
import { invalidate, q } from "@/api/query-keys";
import { CommentSection } from "@/components/comments/CommentSection";
import { Markdown } from "@/components/Markdown";
import { normalizePropertyValue } from "@/components/properties/PropertyFields";
import { StatusMessage } from "@/components/StatusMessage";
import { TaskEditSkeleton } from "@/components/skeletons/PageSkeletons";
import { MoveTaskDialog } from "@/components/tasks/MoveTaskDialog";
import { TaskChecklist } from "@/components/tasks/TaskChecklist";
import {
  emptyTaskFormValue,
  serializeTaskFormValue,
  TaskForm,
  type TaskFormValue,
} from "@/components/tasks/TaskForm";
import { ToolBreadcrumb } from "@/components/tools/ToolBreadcrumb";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { useActiveGuildId } from "@/hooks/useActiveGuildId";
import { useAIEnabled } from "@/hooks/useAIEnabled";
import { useAuth } from "@/hooks/useAuth";
import { useCanonicalInitiativeId } from "@/hooks/useCanonicalInitiativeId";
import { useComments } from "@/hooks/useComments";
import { useDateLocale } from "@/hooks/useDateLocale";
import { useGuilds } from "@/hooks/useGuilds";
import { useProject, useProjectTaskStatuses, useWritableProjects } from "@/hooks/useProjects";
import { useRelativeTime } from "@/hooks/useRelativeTime";
import { useServerForm } from "@/hooks/useServerForm";
import {
  useDeleteTask,
  useDuplicateTask,
  useGenerateTaskDescription,
  useMoveTask,
  useTask,
  useUpdateTask,
} from "@/hooks/useTasks";
import { toast } from "@/lib/chesterToast";
import { dateRangeBounds } from "@/lib/dateRange";
import { getHttpStatus } from "@/lib/errorMessage";
import { useGuildPath } from "@/lib/guildUrl";
import { hasWriteAccess } from "@/lib/permissions";
import { queryClient } from "@/lib/queryClient";
import { taskRoute, toolDetailRoute, toolListRoute } from "@/lib/tools";
import {
  getAvatarSrc,
  getInitialsForUser,
  getUserDisplayName,
  isAnonymizedUser,
} from "@/lib/userDisplay";

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

/** Build the controlled ``propertyValues`` map from the task's server rows. */
const seedPropertyValues = (properties: PropertySummary[]): Record<number, unknown> => {
  const seeded: Record<number, unknown> = {};
  for (const property of properties) {
    seeded[property.property_id] = normalizePropertyValue(property);
  }
  return seeded;
};

/** The subset of a task read the form seeds from (shared by TaskRead / TaskListRead). */
type TaskFormSource = Omit<
  Pick<
    TaskRead,
    | "title"
    | "description"
    | "task_status_id"
    | "priority"
    | "start_date"
    | "due_date"
    | "recurrence"
    | "recurrence_strategy"
    | "tags"
    | "properties"
  >,
  "assignees"
> & { assignees?: { id: number }[] | null };

/** The canonical form value for a loaded/saved task. */
const formValueFromTask = (task: TaskFormSource): TaskFormValue => ({
  title: task.title,
  description: task.description ?? "",
  statusId: task.task_status_id,
  priority: task.priority,
  assigneeIds: task.assignees?.map((assignee) => assignee.id) ?? [],
  startDate: toLocalInputValue(task.start_date),
  dueDate: toLocalInputValue(task.due_date),
  recurrence: task.recurrence ?? null,
  recurrenceStrategy: task.recurrence_strategy ?? "fixed",
  tags: task.tags ?? [],
  properties: task.properties ?? [],
  propertyValues: seedPropertyValues(task.properties ?? []),
});

type MoveTaskVariables = {
  targetProjectId: number;
  targetProjectName?: string;
  previousProjectId: number | null;
};

export const TaskEditPage = () => {
  const { taskId, projectId: projectIdParam } = useParams({ strict: false }) as {
    taskId: string;
    projectId?: string;
  };
  const parsedTaskId = Number(taskId);
  const router = useRouter();
  const guildId = useActiveGuildId();
  const { user: currentUser } = useAuth();
  useGuilds();
  const { t } = useTranslation(["tasks", "common", "properties"]);
  const gp = useGuildPath();
  const dateLocale = useDateLocale();
  const { isEnabled: aiEnabled } = useAIEnabled();

  const [isEditingDescription, setIsEditingDescription] = useState(false);
  // Lets the delete/move/duplicate flows navigate without tripping the
  // unsaved-changes guard.
  const bypassGuardRef = useRef(false);
  const [isMoveDialogOpen, setIsMoveDialogOpen] = useState(false);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [moveContext, setMoveContext] = useState<MoveTaskVariables | null>(null);

  const taskQuery = useTask(parsedTaskId);

  const projectId = projectIdParam ? Number(projectIdParam) : taskQuery.data?.project_id;
  const projectQuery = useProject(projectId ?? null);
  // Where a delete returns to. Held in a ref because a task opened without a
  // project in its path resolves its project through the task query, and the
  // delete clears that before the success handler navigates. The task's own
  // project wins over the one in the path: moving the task rewrites the former
  // and leaves the latter behind.
  const lastProjectIdRef = useRef<number | null>(null);
  const taskProjectId = taskQuery.data?.project_id;
  useEffect(() => {
    const owner = typeof taskProjectId === "number" ? taskProjectId : projectId;
    if (typeof owner === "number" && Number.isFinite(owner)) {
      lastProjectIdRef.current = owner;
    }
  }, [taskProjectId, projectId]);

  const taskStatusesQuery = useProjectTaskStatuses(projectId ?? null);

  const commentsQueryParams = { task_id: parsedTaskId };
  const commentsQueryKey = getListCommentsApiV1GGuildIdCommentsGetQueryKey(
    guildId,
    commentsQueryParams
  );
  const commentsQuery = useComments(commentsQueryParams, {
    enabled: Number.isFinite(parsedTaskId),
  });

  // Aliased early so handleSubmit / effective* derivations both see it.
  // The duplicate declaration further down was kept until this fix; the
  // late-render computations now read this single source of truth.
  const task = taskQuery.data;

  // Every field this page saves, filled in from the task and kept there until
  // it is saved. The values are deeper than fields — a recurrence, tag rows, a
  // map of property values — and the form's own idea of equality already
  // exists, so it answers "has this moved" too.
  const form = useServerForm(
    task,
    (loaded) => (loaded ? formValueFromTask(loaded) : emptyTaskFormValue()),
    task?.id,
    (a, b) => serializeTaskFormValue(a) === serializeTaskFormValue(b)
  );
  const {
    title,
    description,
    assigneeIds,
    startDate,
    dueDate,
    tags,
    propertyValues,
    statusId: effectiveStatusId,
    priority: effectivePriority,
    recurrence: effectiveRecurrence,
    recurrenceStrategy: effectiveRecurrenceStrategy,
  } = form.values;
  const attachedProperties = form.values.properties;
  const setDescription = (next: string) => form.set({ description: next });

  const isProjectContextLoading =
    Number.isFinite(projectId) && projectQuery.isLoading && !projectQuery.data;

  const updateTask = useUpdateTask({
    onSuccess: (updatedTask) => {
      setIsEditingDescription(false);
      form.settle(formValueFromTask(updatedTask));
      toast.success(t("edit.taskUpdated"));
    },
  });

  const duplicateTask = useDuplicateTask({
    onSuccess: (newTask) => {
      toast.success(t("edit.taskDuplicated"));
      bypassGuardRef.current = true;
      router.navigate({
        to: gp(taskRoute(initiativeId, newTask.project_id, newTask.id)),
      });
    },
  });

  const deleteTask = useDeleteTask({
    onSuccess: () => {
      toast.success(t("edit.taskDeleted"));
      bypassGuardRef.current = true;
      // Back to the project the task lived in — the projects list is a step
      // further out than the user asked to go.
      const returnProjectId = lastProjectIdRef.current;
      router.navigate({
        to: gp(
          returnProjectId === null
            ? toolListRoute(Tool.project, initiativeId)
            : toolDetailRoute(Tool.project, initiativeId, returnProjectId)
        ),
      });
    },
  });

  const moveTask = useMoveTask({
    onSuccess: (updatedTask) => {
      queryClient.setQueryData<TaskRead>(
        getReadTaskApiV1GGuildIdTasksTaskIdGetQueryKey(guildId, parsedTaskId),
        updatedTask
      );
      const previousProjectId = moveContext?.previousProjectId;
      if (typeof previousProjectId === "number") {
        void invalidate(q.projectTaskStatuses(previousProjectId), q.project(previousProjectId));
      }
      if (typeof moveContext?.targetProjectId === "number") {
        void invalidate(
          q.projectTaskStatuses(moveContext.targetProjectId),
          q.project(moveContext.targetProjectId)
        );
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
      queryClient.setQueryData<TaskRead>(
        getReadTaskApiV1GGuildIdTasksTaskIdGetQueryKey(guildId, parsedTaskId),
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

  // TaskForm flags the inverted range; blocking submit keeps it out of the API.
  const { isInverted: datesInverted } = dateRangeBounds(startDate, dueDate);

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (isReadOnly) {
      return;
    }
    if (!Number.isFinite(effectiveStatusId)) {
      toast.error(t("edit.taskStatusRequired"));
      return;
    }
    if (datesInverted) {
      return;
    }
    const payload: Record<string, unknown> = {
      title,
      description: description || null,
      task_status_id: effectiveStatusId,
      priority: effectivePriority,
      assignee_ids: assigneeIds,
      start_date: startDate ? new Date(startDate).toISOString() : null,
      due_date: dueDate ? new Date(dueDate).toISOString() : null,
      recurrence: effectiveRecurrence,
      recurrence_strategy: effectiveRecurrence ? effectiveRecurrenceStrategy : "fixed",
      tag_ids: tags.map((tag) => tag.id),
      property_values: attachedProperties.map((property) => ({
        property_id: property.property_id,
        value: propertyValues[property.property_id] ?? null,
      })),
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

  const project = projectQuery.data;
  // A task's initiative is its project's. The path supplies it while that
  // loads, and a URL naming a different one is corrected in place.
  const initiativeId = useCanonicalInitiativeId(project?.initiative_id);

  // Creator metadata for the inline "Created by …" chip in the title row.
  // The creator summary rides the task read payload; fall back to
  // ``User #<id>`` if the author has since left the guild (creator absent).
  const creator = task?.creator ?? null;

  const creationContext = useMemo(() => {
    if (!task?.created_at) return null;
    const anonymized = isAnonymizedUser(creator);
    const displayName = creator
      ? getUserDisplayName(creator)
      : task.created_by != null
        ? `User #${task.created_by}`
        : null;
    const avatarSrc = creator && !anonymized ? getAvatarSrc(creator) : undefined;
    return {
      createdAt: new Date(task.created_at),
      displayName,
      avatarSrc,
      anonymized,
      initials: getInitialsForUser(creator),
      creatorId: creator?.id ?? null,
    };
  }, [task?.created_at, task?.created_by, creator]);

  // The relative "N ago" label refreshes in place via the shared clock; the
  // absolute date never changes so it's formatted inline.
  const relativeCreatedAt = useRelativeTime(creationContext?.createdAt);
  const creationMeta = creationContext
    ? {
        ...creationContext,
        relative: relativeCreatedAt,
        absolute: format(creationContext.createdAt, "PPpp", { locale: dateLocale }),
      }
    : null;

  // Pure DAC: permissions inherited from project. Server-computed — already
  // capped at "read" when the guild's content is frozen (read_only status).
  const hasWritePermission = hasWriteAccess(project?.my_permission_level);
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

  // What the unsaved-changes guard asks: do the fields still say what the task
  // says? (Kept before the early returns so the guard hooks below run
  // unconditionally.)
  const isDirty =
    !isReadOnly &&
    task !== undefined &&
    serializeTaskFormValue(form.values) !== serializeTaskFormValue(formValueFromTask(task));

  // Block in-app navigation while there are unsaved edits (unless a delete /
  // move / duplicate flow explicitly opted out via bypassGuardRef).
  // Also guards full-page unloads. `enableBeforeUnload` is what asks about a
  // reload or a closed tab, and it has to repeat the condition: the router
  // defaults it to true and never consults `shouldBlockFn` for an unload, so
  // without it every reload of this page prompts.
  const blocker = useBlocker({
    shouldBlockFn: () => isDirty && !bypassGuardRef.current,
    enableBeforeUnload: () => isDirty && !bypassGuardRef.current,
    withResolver: true,
  });

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
    return <TaskEditSkeleton label={t("edit.loadingTask")} />;
  }

  if (taskQuery.isError || taskStatusesQuery.isError || !taskQuery.data) {
    const status = getHttpStatus(taskQuery.error) ?? getHttpStatus(taskStatusesQuery.error);

    if (status === 404) {
      return (
        <StatusMessage
          icon={<SearchX />}
          title={t("edit.notFound")}
          description={t("edit.notFoundDescription")}
          backTo={gp(toolListRoute(Tool.project, initiativeId))}
          backLabel={t("edit.backToProjects")}
        />
      );
    }
    if (status === 403) {
      return (
        <StatusMessage
          icon={<ShieldAlert />}
          title={t("edit.noAccess")}
          description={t("edit.noAccessDescription")}
          backTo={gp(toolListRoute(Tool.project, initiativeId))}
          backLabel={t("edit.backToProjects")}
        />
      );
    }
    return (
      <StatusMessage
        icon={<AlertCircle />}
        title={t("edit.loadError")}
        backTo={gp(toolListRoute(Tool.project, initiativeId))}
        backLabel={t("edit.backToProjects")}
      />
    );
  }

  if (Number.isFinite(projectId) && projectQuery.isError) {
    return (
      <StatusMessage
        icon={<AlertCircle />}
        title={t("edit.loadProjectError")}
        backTo={gp(toolListRoute(Tool.project, initiativeId))}
        backLabel={t("edit.backToProjects")}
      />
    );
  }

  const taskStatuses = taskStatusesQuery.data ?? [];

  // A task keeps the status it was given even after the project drops that
  // column, and the select can only name a status the list contains. Carry the
  // task's own snapshot into the options in that case, so the editor still
  // says what status the task is in rather than falling back to a placeholder.
  // Not a hook: this sits below the loading guards above, which return early.
  const statusOptions =
    task?.task_status &&
    task.task_status.id === effectiveStatusId &&
    !taskStatuses.some((item) => item.id === effectiveStatusId)
      ? [...taskStatuses, task.task_status]
      : taskStatuses;
  // Prefer the project's status list (authoritative; reflects renames/colors)
  // but fall back to the task's own embedded ``task_status`` snapshot so the
  // badge + select trigger render correctly during the window between
  // "task loaded" and "project statuses loaded" — and as a safety net if
  // the status was archived out of the list since the task was last saved.
  // Delete and move are excluded: their confirm/move dialogs stay open and
  // already show the mutation's own loading state.
  const menuActionPending = duplicateTask.isPending || toggleArchive.isPending;

  // Assemble the shared TaskForm value from the page's individual states. The
  // effective* fallbacks keep the form from flashing defaults during the
  // one-render gap between "task loaded" and "load effect ran".
  const formValue = form.values;
  const handleFormChange = (next: TaskFormValue) => form.set(next);

  // The editor's richer description block (markdown preview + AI generate +
  // edit/preview toggle), passed to TaskForm as its description slot.
  const descriptionSlot = (
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
        <div className="rounded-md border border-border/70 border-dashed bg-muted/40 px-3 py-2">
          <Markdown content={description} />
        </div>
      ) : (
        <p className="text-muted-foreground text-sm italic">
          {isReadOnly ? t("edit.noDescriptionReadOnly") : t("edit.noDescription")}
        </p>
      )}
    </div>
  );

  return (
    <div className="space-y-6">
      <ToolBreadcrumb
        tool={Tool.project}
        initiativeId={initiativeId}
        trail={[
          ...(project
            ? [
                {
                  label: project.name,
                  to: toolDetailRoute(Tool.project, initiativeId, project.id),
                },
              ]
            : []),
          { label: title || task?.title },
        ]}
      />
      {/* The task's title and status are rendered once each, by the form's own
          title field and status select. This row carries only the byline. */}
      <h1 className="sr-only">{title || task?.title}</h1>
      <div className="space-y-3">
        <div className="flex flex-wrap items-center gap-3">
          {creationMeta ? (
            <TooltipProvider delayDuration={200}>
              <Tooltip>
                <TooltipTrigger asChild>
                  <div className="ml-auto flex items-center gap-2 text-muted-foreground text-xs">
                    {creationMeta.displayName ? (
                      <Avatar className="h-5 w-5 border text-[10px]">
                        {creationMeta.avatarSrc ? (
                          <AvatarImage
                            src={creationMeta.avatarSrc}
                            alt={creationMeta.displayName}
                          />
                        ) : null}
                        <AvatarFallback
                          userId={creationMeta.anonymized ? null : creationMeta.creatorId}
                        >
                          {creationMeta.initials}
                        </AvatarFallback>
                      </Avatar>
                    ) : null}
                    <span>
                      {creationMeta.displayName
                        ? t("edit.createdBy", {
                            name: creationMeta.displayName,
                            time: creationMeta.relative,
                          })
                        : t("edit.createdAt", { time: creationMeta.relative })}
                    </span>
                  </div>
                </TooltipTrigger>
                <TooltipContent>{creationMeta.absolute}</TooltipContent>
              </Tooltip>
            </TooltipProvider>
          ) : null}
        </div>
      </div>

      <div className="flex flex-wrap gap-6">
        <Card className="flex-1 shadow-sm sm:min-w-100">
          <CardContent className="pt-6">
            {isReadOnly && readOnlyMessage ? (
              <p className="rounded-md border border-border bg-muted/50 px-3 py-2 text-muted-foreground text-sm">
                {readOnlyMessage}
              </p>
            ) : null}
            <form className="space-y-6" onSubmit={handleSubmit}>
              <TaskForm
                layout="page"
                disabled={isReadOnly}
                value={formValue}
                onChange={handleFormChange}
                statuses={statusOptions}
                projectId={projectId ?? null}
                initiativeId={project?.initiative_id ?? null}
                currentUserId={currentUser?.id}
                selectedAssignees={task?.assignees}
                descriptionSlot={descriptionSlot}
                recurrenceReferenceDate={dueDate || startDate || task?.due_date || task?.start_date}
              />

              {/* Save and cancel are the only actions that earn a button here;
                  everything else a task supports lives behind the overflow
                  menu so the row stays readable at any width. */}
              <div className="flex flex-wrap items-center gap-3">
                <Button
                  type="submit"
                  disabled={updateTask.isPending || isReadOnly || datesInverted}
                >
                  <Save className="h-4 w-4" />
                  {updateTask.isPending ? t("edit.saving") : t("edit.saveTask")}
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  onClick={() =>
                    router.navigate({
                      to: gp(toolDetailRoute(Tool.project, initiativeId, projectId as number)),
                    })
                  }
                >
                  <X className="h-4 w-4" />
                  {t("common:cancel")}
                </Button>
                {!isReadOnly ? (
                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      {/* Duplicate and archive dismiss the menu that holds their
                          own pending label, and neither opens a dialog to carry
                          one, so the trigger reports their progress instead. */}
                      <Button
                        type="button"
                        variant="outline"
                        size="icon"
                        className="ml-auto"
                        aria-label={t("common:toolbar.moreActions")}
                        aria-busy={menuActionPending}
                      >
                        {menuActionPending ? (
                          <Loader2 className="h-4 w-4 animate-spin" />
                        ) : (
                          <MoreHorizontal className="h-4 w-4" />
                        )}
                      </Button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end">
                      <DropdownMenuItem
                        disabled={moveTask.isPending}
                        onSelect={() => setIsMoveDialogOpen(true)}
                      >
                        <FolderInput className="h-4 w-4" />
                        {t("edit.moveToProject")}
                      </DropdownMenuItem>
                      <DropdownMenuItem
                        disabled={duplicateTask.isPending}
                        onSelect={() => {
                          duplicateTask.mutate(parsedTaskId);
                        }}
                      >
                        <Copy className="h-4 w-4" />
                        {duplicateTask.isPending ? t("edit.duplicating") : t("edit.duplicateTask")}
                      </DropdownMenuItem>
                      <DropdownMenuItem
                        disabled={toggleArchive.isPending}
                        onSelect={() =>
                          toggleArchive.mutate({
                            taskId: parsedTaskId,
                            data: { is_archived: !task?.is_archived } as never,
                          })
                        }
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
                      </DropdownMenuItem>
                      <DropdownMenuSeparator />
                      <DropdownMenuItem
                        className="text-destructive focus:text-destructive"
                        disabled={deleteTask.isPending}
                        onSelect={() => setShowDeleteConfirm(true)}
                      >
                        <Trash2 className="h-4 w-4" />
                        {deleteTask.isPending ? t("edit.deleting") : t("edit.deleteTask")}
                      </DropdownMenuItem>
                    </DropdownMenuContent>
                  </DropdownMenu>
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
        </div>
      </div>

      {/* The thread gets the whole row rather than half of one: a conversation
          read in a column this narrow wraps every reply. */}
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

      <MoveTaskDialog
        open={isMoveDialogOpen}
        onOpenChange={setIsMoveDialogOpen}
        projects={writableProjects}
        currentProjectId={task?.project_id ?? null}
        isLoading={writableProjectsQuery.isLoading}
        hasError={Boolean(writableProjectsQuery.isError)}
        isSaving={moveTask.isPending}
        onConfirm={handleMoveTask}
      />

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

      <ConfirmDialog
        open={blocker.status === "blocked"}
        onOpenChange={(open) => {
          if (!open) blocker.reset?.();
        }}
        title={t("edit.unsavedTitle")}
        description={t("edit.unsavedBody")}
        confirmLabel={t("edit.unsavedLeave")}
        cancelLabel={t("edit.unsavedStay")}
        onConfirm={() => blocker.proceed?.()}
        destructive
      />
    </div>
  );
};
