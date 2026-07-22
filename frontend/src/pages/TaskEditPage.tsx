import { Link, useBlocker, useParams, useRouter } from "@tanstack/react-router";
import { format, formatDistanceToNow } from "date-fns";
import {
  AlertCircle,
  Archive,
  ArchiveRestore,
  Copy,
  FolderInput,
  Loader2,
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
import type {
  CommentRead,
  PropertySummary,
  TagSummary,
  TaskListRead,
  TaskListReadRecurrenceStrategy,
  TaskPriority,
  TaskRead,
  TaskRecurrenceOutput,
} from "@/api/generated/initiativeAPI.schemas";
import { getReadTaskApiV1GGuildIdTasksTaskIdGetQueryKey } from "@/api/generated/tasks/tasks";
import { invalidateProject, invalidateProjectTaskStatuses } from "@/api/query-keys";
import { CommentSection } from "@/components/comments/CommentSection";
import { Markdown } from "@/components/Markdown";
import { normalizePropertyValue } from "@/components/properties/PropertyFields";
import { StatusMessage } from "@/components/StatusMessage";
import { MoveTaskDialog } from "@/components/tasks/MoveTaskDialog";
import { TaskChecklist } from "@/components/tasks/TaskChecklist";
import { serializeTaskFormValue, TaskForm, type TaskFormValue } from "@/components/tasks/TaskForm";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
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
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { useActiveGuildId } from "@/hooks/useActiveGuildId";
import { useAIEnabled } from "@/hooks/useAIEnabled";
import { useAuth } from "@/hooks/useAuth";
import { useComments } from "@/hooks/useComments";
import { useDateLocale } from "@/hooks/useDateLocale";
import { useGuilds } from "@/hooks/useGuilds";
import { useProject, useProjectTaskStatuses, useWritableProjects } from "@/hooks/useProjects";
import {
  useDeleteTask,
  useDuplicateTask,
  useGenerateTaskDescription,
  useMoveTask,
  useTask,
  useUpdateTask,
} from "@/hooks/useTasks";
import { toast } from "@/lib/chesterToast";
import { getHttpStatus } from "@/lib/errorMessage";
import { useGuildPath } from "@/lib/guildUrl";
import { queryClient } from "@/lib/queryClient";
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
  const { taskId } = useParams({ strict: false }) as { taskId: string };
  const parsedTaskId = Number(taskId);
  const router = useRouter();
  const guildId = useActiveGuildId();
  const { user: currentUser } = useAuth();
  useGuilds();
  const { t } = useTranslation(["tasks", "common", "properties"]);
  const gp = useGuildPath();
  const dateLocale = useDateLocale();
  const { isEnabled: aiEnabled } = useAIEnabled();

  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [isEditingDescription, setIsEditingDescription] = useState(false);
  const [statusId, setStatusId] = useState<number | null>(null);
  // null/undefined are "uninitialized" sentinels here — the useEffect that
  // copies task.* into local state runs after the first render, so the
  // form would otherwise flash the initial defaults ("medium" / no
  // recurrence / "fixed") before snapping to the real values. Reading
  // through effective* below falls back to the task data on the first
  // render and uses local state once the user has interacted.
  const [priority, setPriority] = useState<TaskPriority | null>(null);
  const [assigneeIds, setAssigneeIds] = useState<number[]>([]);
  const [startDate, setStartDate] = useState<string>("");
  const [dueDate, setDueDate] = useState<string>("");
  // Recurrence uses ``undefined`` as the uninitialized sentinel because
  // ``null`` is a legitimate user choice meaning "no recurrence".
  const [recurrence, setRecurrence] = useState<TaskRecurrenceOutput | null | undefined>(undefined);
  const [recurrenceStrategy, setRecurrenceStrategy] =
    useState<TaskListReadRecurrenceStrategy | null>(null);
  const [tags, setTags] = useState<TagSummary[]>([]);
  // Attached property rows (real server rows + locally-added stubs) and their
  // controlled values. Both seed from the task and are batched into the main
  // Save (PATCH) rather than saved immediately.
  const [attachedProperties, setAttachedProperties] = useState<PropertySummary[]>([]);
  const [propertyValues, setPropertyValues] = useState<Record<number, unknown>>({});
  // Serialized snapshot of the last-saved form value; dirty state is a diff
  // against it. Set whenever the form is seeded (task load / save success).
  const [savedSnapshot, setSavedSnapshot] = useState<string | null>(null);
  // Lets the delete/move/duplicate flows navigate without tripping the
  // unsaved-changes guard.
  const bypassGuardRef = useRef(false);
  // Track which task the form was last seeded from, and whether it currently
  // holds unsaved edits, so a background refetch doesn't overwrite them.
  const seededTaskIdRef = useRef<number | null>(null);
  const isDirtyRef = useRef(false);
  const [isMoveDialogOpen, setIsMoveDialogOpen] = useState(false);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [moveContext, setMoveContext] = useState<MoveTaskVariables | null>(null);

  const taskQuery = useTask(parsedTaskId);

  const projectId = taskQuery.data?.project_id;
  const projectQuery = useProject(projectId ?? null);

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

  // Mirror the status fix for priority / recurrence / recurrenceStrategy:
  // local state is the source of truth once the useEffect has copied it,
  // otherwise read straight from task so the form doesn't flash a default
  // before snapping to the real value.
  const effectivePriority: TaskPriority = priority ?? task?.priority ?? "medium";
  const effectiveRecurrence: TaskRecurrenceOutput | null =
    recurrence !== undefined ? recurrence : (task?.recurrence ?? null);
  const effectiveRecurrenceStrategy: TaskListReadRecurrenceStrategy =
    recurrenceStrategy ?? task?.recurrence_strategy ?? "fixed";

  useEffect(() => {
    if (taskQuery.data) {
      const task = taskQuery.data;
      // Don't clobber unsaved edits: a background refetch of the same task
      // must not overwrite pending field/tag/property changes. Only reseed
      // when this is a different task, or the form has no unsaved edits.
      const isNewTask = seededTaskIdRef.current !== task.id;
      if (!isNewTask && isDirtyRef.current) {
        return;
      }
      seededTaskIdRef.current = task.id;
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
      setAttachedProperties(task.properties ?? []);
      setPropertyValues(seedPropertyValues(task.properties ?? []));
      setSavedSnapshot(serializeTaskFormValue(formValueFromTask(task)));
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
      setTags(updatedTask.tags ?? []);
      setAttachedProperties(updatedTask.properties ?? []);
      setPropertyValues(seedPropertyValues(updatedTask.properties ?? []));
      setSavedSnapshot(serializeTaskFormValue(formValueFromTask(updatedTask)));
      toast.success(t("edit.taskUpdated"));
    },
  });

  const duplicateTask = useDuplicateTask({
    onSuccess: (newTask) => {
      toast.success(t("edit.taskDuplicated"));
      bypassGuardRef.current = true;
      router.navigate({ to: gp(`/tasks/${newTask.id}`) });
    },
  });

  const deleteTask = useDeleteTask({
    onSuccess: () => {
      toast.success(t("edit.taskDeleted"));
      bypassGuardRef.current = true;
      router.navigate({ to: gp(`/projects/${projectId}`) });
    },
  });

  const moveTask = useMoveTask({
    onSuccess: (updatedTask) => {
      queryClient.setQueryData<TaskListRead>(
        getReadTaskApiV1GGuildIdTasksTaskIdGetQueryKey(guildId, parsedTaskId),
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

  // Creator metadata for the inline "Created by …" chip in the title row.
  // The creator summary rides the task read payload; fall back to
  // ``User #<id>`` if the author has since left the guild (creator absent).
  const creator = task?.creator ?? null;

  const creationContext = useMemo(() => {
    if (!task?.created_at) return null;
    const anonymized = isAnonymizedUser(creator);
    const displayName = creator
      ? getUserDisplayName(creator)
      : task.created_by_id != null
        ? `User #${task.created_by_id}`
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
  }, [task?.created_at, task?.created_by_id, creator]);

  // Tick once a minute so the "N ago" label stays fresh while the page is
  // open — ``formatDistanceToNow`` reads ``Date.now()`` at call time, so a
  // bare state update is enough to re-render with a current value.
  const [, setRelativeTick] = useState(0);
  useEffect(() => {
    if (!creationContext) return;
    const id = setInterval(() => setRelativeTick((n) => n + 1), 60_000);
    return () => clearInterval(id);
  }, [creationContext]);

  // Computed each render (cheap) so the tick above actually shows up.
  const creationMeta = creationContext
    ? {
        ...creationContext,
        relative: formatDistanceToNow(creationContext.createdAt, {
          addSuffix: true,
          locale: dateLocale,
        }),
        absolute: format(creationContext.createdAt, "PPpp", { locale: dateLocale }),
      }
    : null;

  // Pure DAC: permissions inherited from project. Server-computed — already
  // capped at "read" when the guild's content is frozen (read_only status).
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

  // Dirty tracking for the unsaved-changes guard: compare the current field
  // values against the last-saved snapshot. Computed from the individual
  // states + effective* fallbacks (kept before the early returns so the
  // guard hooks below run unconditionally).
  const currentSnapshot = serializeTaskFormValue({
    title,
    description,
    statusId: statusId ?? task?.task_status_id ?? null,
    priority: effectivePriority,
    assigneeIds,
    startDate,
    dueDate,
    recurrence: effectiveRecurrence,
    recurrenceStrategy: effectiveRecurrenceStrategy,
    tags,
    properties: attachedProperties,
    propertyValues,
  });
  const isDirty = !isReadOnly && savedSnapshot !== null && currentSnapshot !== savedSnapshot;
  // Mirror into a ref so the task-load effect can read the latest dirtiness
  // without adding it to the effect's dependency list.
  isDirtyRef.current = isDirty;

  // Block in-app navigation while there are unsaved edits (unless a delete /
  // move / duplicate flow explicitly opted out via bypassGuardRef).
  const blocker = useBlocker({
    shouldBlockFn: () => isDirty && !bypassGuardRef.current,
    withResolver: true,
  });

  // Guard full-page unloads (reload / tab close) while dirty.
  useEffect(() => {
    if (!isDirty) return;
    const handler = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [isDirty]);

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
    const status = getHttpStatus(taskQuery.error) ?? getHttpStatus(taskStatusesQuery.error);

    if (status === 404) {
      return (
        <StatusMessage
          icon={<SearchX />}
          title={t("edit.notFound")}
          description={t("edit.notFoundDescription")}
          backTo={gp("/projects")}
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
          backTo={gp("/projects")}
          backLabel={t("edit.backToProjects")}
        />
      );
    }
    return (
      <StatusMessage
        icon={<AlertCircle />}
        title={t("edit.loadError")}
        backTo={gp("/projects")}
        backLabel={t("edit.backToProjects")}
      />
    );
  }

  if (Number.isFinite(projectId) && projectQuery.isError) {
    return (
      <StatusMessage
        icon={<AlertCircle />}
        title={t("edit.loadProjectError")}
        backTo={gp("/projects")}
        backLabel={t("edit.backToProjects")}
      />
    );
  }

  const taskStatuses = taskStatusesQuery.data ?? [];
  // Use the local statusId once the useEffect has copied it out of the task,
  // otherwise read straight from task.task_status_id so the first render has
  // a value (the useEffect lag previously left the badge blank).
  const effectiveStatusId = statusId ?? task?.task_status_id ?? null;
  // Prefer the project's status list (authoritative; reflects renames/colors)
  // but fall back to the task's own embedded ``task_status`` snapshot so the
  // badge + select trigger render correctly during the window between
  // "task loaded" and "project statuses loaded" — and as a safety net if
  // the status was archived out of the list since the task was last saved.
  const currentStatus =
    taskStatuses.find((item) => item.id === effectiveStatusId) ??
    (task && task.task_status_id === effectiveStatusId ? task.task_status : null);

  // Assemble the shared TaskForm value from the page's individual states. The
  // effective* fallbacks keep the form from flashing defaults during the
  // one-render gap between "task loaded" and "load effect ran".
  const formValue: TaskFormValue = {
    title,
    description,
    statusId: effectiveStatusId,
    priority: effectivePriority,
    assigneeIds,
    startDate,
    dueDate,
    recurrence: effectiveRecurrence,
    recurrenceStrategy: effectiveRecurrenceStrategy,
    tags,
    properties: attachedProperties,
    propertyValues,
  };

  const handleFormChange = (next: TaskFormValue) => {
    setTitle(next.title);
    setDescription(next.description);
    setStatusId(next.statusId);
    setPriority(next.priority);
    setAssigneeIds(next.assigneeIds);
    setStartDate(next.startDate);
    setDueDate(next.dueDate);
    setRecurrence(next.recurrence);
    setRecurrenceStrategy(next.recurrenceStrategy);
    setTags(next.tags);
    setAttachedProperties(next.properties);
    setPropertyValues(next.propertyValues);
  };

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
          <h1 className="font-semibold text-3xl tracking-tight">{title || task?.title}</h1>
          <Badge variant="secondary">{currentStatus?.name ?? t("edit.statusBadge")}</Badge>
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
                statuses={taskStatuses}
                projectId={projectId ?? null}
                initiativeId={project?.initiative_id ?? null}
                currentUserId={currentUser?.id}
                selectedAssignees={task?.assignees}
                descriptionSlot={descriptionSlot}
                recurrenceReferenceDate={dueDate || startDate || task?.due_date || task?.start_date}
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
