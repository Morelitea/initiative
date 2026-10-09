import { useBlocker, useParams, useRouter } from "@tanstack/react-router";
import { format } from "date-fns";
import { AlertCircle } from "lucide-react";
import { type FormEvent, useEffect, useId, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import type { PropertySummary, TaskRead } from "@/api/generated/initiativeAPI.schemas";
import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { getReadTaskQueryKey, readTask } from "@/api/generated/tasks/tasks";
import { invalidate, q } from "@/api/query-keys";
import { normalizePropertyValue } from "@/components/properties/propertyHelpers";
import { useScopePrompt } from "@/components/recurrence/OccurrenceScopeDialog";
import { StatusMessage } from "@/components/StatusMessage";
import { TaskEditSkeleton } from "@/components/skeletons/PageSkeletons";
import { ToolAccessStatus } from "@/components/ToolAccessStatus";
import { MoveTaskDialog } from "@/components/tasks/MoveTaskDialog";
import { type TaskPageContext, taskPageParts } from "@/components/tasks/parts";
import {
  emptyTaskFormValue,
  serializeTaskFormValue,
  type TaskFormValue,
  taskFormPropertyValues,
} from "@/components/tasks/TaskForm";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { useAIEnabled } from "@/hooks/useAIEnabled";
import { useArchiveEntity, useUnarchiveEntity } from "@/hooks/useArchive";
import { useAuth } from "@/hooks/useAuth";
import { useCanonicalInitiativeId } from "@/hooks/useCanonicalInitiativeId";
import { useComments, useCommentsCache } from "@/hooks/useComments";
import { useCommunities } from "@/hooks/useCommunities";
import { useDateLocale } from "@/hooks/useDateLocale";
import { useInitiative } from "@/hooks/useInitiatives";
import { useReadOnOpen } from "@/hooks/useNotifications";
import { useProject, useProjectTaskStatuses, useWritableProjects } from "@/hooks/useProjects";
import { useRelativeTime } from "@/hooks/useRelativeTime";
import { useServerForm } from "@/hooks/useServerForm";
import { useTaskBlocks } from "@/hooks/useTaskBlocks";
import {
  useDeleteTask,
  useDuplicateTask,
  useGenerateTaskDescription,
  useMoveTask,
  useSkipTask,
  useTask,
  useUpdateTask,
} from "@/hooks/useTasks";
import { useCommunityPath } from "@/lib/communityUrl";
import { dateRangeBounds } from "@/lib/dateRange";
import { getHttpStatus } from "@/lib/errorMessage";
import { toast } from "@/lib/mascotToast";
import { queryClient } from "@/lib/queryClient";
import { fromStored, rulePayload } from "@/lib/recurrence";
import { Section } from "@/lib/templates/Section";
import { dateTimePattern } from "@/lib/timeFormat";
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
    | "recurrence_shift"
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
  recurrence: fromStored(task.recurrence, task.due_date ?? task.start_date, task.recurrence_shift),
  recurrenceStrategy: task.recurrence_strategy ?? "fixed",
  tags: task.tags ?? [],
  properties: task.properties ?? [],
  propertyValues: seedPropertyValues(task.properties ?? []),
});

/** The fields an edit of a repeating task can keep from the rest of its series. */
const seriesFields = (value: TaskFormValue) =>
  JSON.stringify([
    value.title,
    value.description,
    value.priority,
    [...value.assigneeIds].sort(),
    value.startDate,
    value.dueDate,
    value.tags.map((tag) => tag.id).sort(),
  ]);

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
  const communityId = useActiveCommunityId();
  const { user: currentUser } = useAuth();
  useCommunities();
  const { t } = useTranslation(["tasks", "common", "properties"]);
  const gp = useCommunityPath();
  const dateLocale = useDateLocale();
  const { isEnabled: aiEnabled } = useAIEnabled();

  // Lets the delete/move/duplicate flows navigate without tripping the
  // unsaved-changes guard.
  const bypassGuardRef = useRef(false);
  const [isMoveDialogOpen, setIsMoveDialogOpen] = useState(false);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [moveContext, setMoveContext] = useState<MoveTaskVariables | null>(null);

  const taskQuery = useTask(parsedTaskId);
  useReadOnOpen("task", taskQuery.data?.id);

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
  const commentsQuery = useComments(commentsQueryParams, {
    enabled: Number.isFinite(parsedTaskId),
  });
  const commentsCache = useCommentsCache(commentsQueryParams);

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
    statusId: effectiveStatusId,
    priority: effectivePriority,
    recurrence: effectiveRecurrence,
    recurrenceStrategy: effectiveRecurrenceStrategy,
  } = form.values;
  const setDescription = (next: string) => form.set({ description: next });

  const isProjectContextLoading =
    Number.isFinite(projectId) && projectQuery.isLoading && !projectQuery.data;

  const updateTask = useUpdateTask();
  const isSaving = updateTask.isPending;

  const duplicateTask = useDuplicateTask({
    onSuccess: (newTask) => {
      toast.success(t("edit.taskDuplicated"));
      bypassGuardRef.current = true;
      router.navigate({
        to: gp(taskRoute(initiativeId, newTask.project_id, newTask.id)),
      });
    },
  });

  const scopePrompt = useScopePrompt();
  const repeating = Boolean(task?.recurrence);

  const skipTask = useSkipTask({
    onSuccess: (skipped) => {
      form.settle(formValueFromTask(skipped));
      toast.success(t("edit.taskSkipped"));
    },
  });

  const deleteTask = useDeleteTask({
    onSuccess: async (_data, { scope }) => {
      // Deleting just this one of a series skips it, so the task is still
      // here, unless it was the series' last and is gone.
      if (scope === "this") {
        try {
          form.settle(formValueFromTask(await readTask(communityId, parsedTaskId)));
          toast.success(t("edit.taskSkipped"));
          return;
        } catch (error) {
          if (getHttpStatus(error) !== 404) {
            toast.success(t("edit.taskSkipped"));
            return;
          }
        }
      }
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
        getReadTaskQueryKey(communityId, parsedTaskId),
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

  const archiveTask = useArchiveEntity({
    onSuccess: () => toast.success(t("edit.taskArchived")),
  });
  const unarchiveTask = useUnarchiveEntity({
    onSuccess: () => toast.success(t("edit.taskUnarchived")),
  });
  const toggleArchive = task?.archived_at !== null ? unarchiveTask : archiveTask;

  const generateDescription = useGenerateTaskDescription({
    onSuccess: (data) => {
      setDescription(data.description);
      toast.success(t("edit.descriptionGenerated"));
    },
  });

  // TaskForm flags the inverted range; blocking submit keeps it out of the API.
  const { isInverted: datesInverted } = dateRangeBounds(startDate, dueDate);

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
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
      ...rulePayload(effectiveRecurrence),
      recurrence_strategy: effectiveRecurrence ? effectiveRecurrenceStrategy : "fixed",
      tag_ids: tags.map((tag) => tag.id),
    };
    const properties = taskFormPropertyValues(form.values);
    // Sent only when they changed, with the task's own fields, so the edit
    // lands whole or not at all.
    if (
      !task ||
      JSON.stringify(properties) !== JSON.stringify(taskFormPropertyValues(formValueFromTask(task)))
    ) {
      payload.properties = properties;
    }
    if (task && repeating && seriesFields(form.values) !== seriesFields(formValueFromTask(task))) {
      const scope = await scopePrompt.ask("edit", { tool: "tasks", count: task.series_size });
      if (scope === null) {
        return;
      }
      payload.scope = scope;
    }
    updateTask.mutate(
      { taskId: parsedTaskId, data: payload as never },
      {
        onSuccess: (updatedTask) => {
          form.settle(formValueFromTask(updatedTask));
          toast.success(t("edit.taskUpdated"));
        },
      }
    );
  };

  const handleDelete = async () => {
    if (!repeating) {
      setShowDeleteConfirm(true);
      return;
    }
    const scope = await scopePrompt.ask("delete", { tool: "tasks", count: task?.series_size });
    if (scope !== null) {
      deleteTask.mutate({ taskId: parsedTaskId, scope });
    }
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
  // ``User #<id>`` if the author has since left the community (creator absent).
  const creator = task?.creator ?? null;

  const creationContext = useMemo(() => {
    if (!task?.created_at) return null;
    const anonymized = isAnonymizedUser(creator);
    const displayName =
      creator || task.created_by != null
        ? getUserDisplayName(creator ?? { id: task.created_by })
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
        absolute: format(creationContext.createdAt, dateTimePattern("PP", { seconds: true }), {
          locale: dateLocale,
        }),
      }
    : null;

  // Pure DAC: permissions inherited from project. Server-computed — already
  // capped at "read" when the community's content is frozen (read_only status).
  const hasWritePermission = Boolean(project?.can.edit);
  const canWriteProject = hasWritePermission;
  const projectIsArchived = (project?.archived_at ?? null) !== null;
  const isReadOnly = !canWriteProject || projectIsArchived;
  const readOnlyMessage = !canWriteProject
    ? t("edit.readOnlyNoAccess")
    : projectIsArchived
      ? t("edit.readOnlyArchived")
      : null;

  const writableProjectsQuery = useWritableProjects({
    enabled: Boolean(canWriteProject && !projectIsArchived),
  });
  // An initiative that keeps its content in keeps its tasks.
  const initiativeQuery = useInitiative(project?.initiative_id ?? null);
  const keptIn = initiativeQuery.data?.keep_content_in;
  const writableProjects = useMemo(
    () =>
      (writableProjectsQuery.data?.items ?? []).filter(
        (candidate) => !keptIn || candidate.initiative_id === project?.initiative_id
      ),
    [writableProjectsQuery.data, keptIn, project?.initiative_id]
  );

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
  const formId = useId();
  // The same object while the task is, so the template reuses what it worked out.
  const sectionData = useMemo(() => (task ? { task } : null), [task]);
  const blockTaskIds = useMemo(() => [parsedTaskId], [parsedTaskId]);
  const blocks = useTaskBlocks("task.page", {
    initiativeId: project?.initiative_id,
    taskIds: blockTaskIds,
  });

  const blocker = useBlocker({
    shouldBlockFn: () => isDirty && !bypassGuardRef.current,
    enableBeforeUnload: () => isDirty && !bypassGuardRef.current,
    withResolver: true,
  });

  if (taskQuery.isLoading || isProjectContextLoading || taskStatusesQuery.isLoading) {
    return <TaskEditSkeleton label={t("edit.loadingTask")} />;
  }

  if (taskQuery.isError || taskStatusesQuery.isError || !taskQuery.data) {
    return (
      <ToolAccessStatus
        error={taskQuery.error ?? taskStatusesQuery.error}
        keys="tasks:edit."
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
  const context: TaskPageContext = {
    form: { values: form.values, set: form.set },
    formId,
    readOnly: isReadOnly,
    readOnlyMessage: isReadOnly ? readOnlyMessage : null,
    statuses: statusOptions,
    project: project ?? null,
    initiativeId,
    currentUserId: currentUser?.id,
    creation: creationMeta,
    save: { submit: handleSubmit, pending: isSaving, blocked: datesInverted },
    cancel: () =>
      router.navigate({
        to: gp(toolDetailRoute(Tool.project, initiativeId, projectId as number)),
      }),
    menu: {
      move: { run: () => setIsMoveDialogOpen(true), pending: moveTask.isPending },
      duplicate: {
        run: () => duplicateTask.mutate(parsedTaskId),
        pending: duplicateTask.isPending,
      },
      archive: {
        run: () => toggleArchive.mutate({ entityType: "task", entityId: parsedTaskId }),
        pending: toggleArchive.isPending,
        archived: task?.archived_at !== null,
      },
      skip: repeating
        ? { run: () => skipTask.mutate(parsedTaskId), pending: skipTask.isPending }
        : null,
      remove: { run: () => void handleDelete(), pending: deleteTask.isPending },
    },
    describe: aiEnabled
      ? {
          run: () => generateDescription.mutate(parsedTaskId),
          pending: generateDescription.isPending,
        }
      : null,
    comments: { query: commentsQuery, cache: commentsCache },
  };

  return (
    <>
      {sectionData ? (
        <Section
          name="task.page"
          data={sectionData}
          context={context}
          parts={taskPageParts}
          blocks={blocks}
        />
      ) : null}

      <MoveTaskDialog
        open={isMoveDialogOpen}
        onOpenChange={setIsMoveDialogOpen}
        projects={writableProjects}
        currentProjectId={task?.project_id ?? null}
        isLoading={writableProjectsQuery.isLoading || initiativeQuery.isLoading}
        hasError={Boolean(writableProjectsQuery.isError)}
        isSaving={moveTask.isPending}
        onConfirm={handleMoveTask}
      />

      {scopePrompt.dialog}

      <ConfirmDialog
        open={showDeleteConfirm}
        onOpenChange={setShowDeleteConfirm}
        title={t("edit.deleteTitle")}
        description={t("edit.deleteDescription")}
        confirmLabel={t("common:delete")}
        onConfirm={() => {
          deleteTask.mutate({ taskId: parsedTaskId });
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
    </>
  );
};
