import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useState } from "react";
import { useTranslation } from "react-i18next";

import { archiveEntityApiV1CGuildIdArchiveEntityTypeEntityIdPost } from "@/api/generated/archive/archive";
import type {
  ArchiveDoneResponse,
  ArchiveResponse,
  ChecklistItem,
  GenerateChecklistResponse,
  GenerateDescriptionResponse,
  ListTasksApiV1CGuildIdTasksGetParams,
  TaskListRead,
  TaskListResponse,
  TaskRead,
  TaskReorderRequest,
  TaskStatusRead,
} from "@/api/generated/initiativeAPI.schemas";
import { getReadSmartChipsApiV1CGuildIdSmartChipsGetQueryKey } from "@/api/generated/smart-chips/smart-chips";
import {
  getListTaskStatusesApiV1CGuildIdProjectsProjectIdTaskStatusesGetQueryKey,
  listTaskStatusesApiV1CGuildIdProjectsProjectIdTaskStatusesGet,
} from "@/api/generated/task-statuses/task-statuses";
import {
  archiveDoneTasksApiV1CGuildIdTasksArchiveDonePost,
  createTaskApiV1CGuildIdTasksPost,
  deleteTaskApiV1CGuildIdTasksTaskIdDelete,
  duplicateTaskApiV1CGuildIdTasksTaskIdDuplicatePost,
  generateTaskChecklistApiV1CGuildIdTasksTaskIdAiChecklistPost,
  generateTaskDescriptionApiV1CGuildIdTasksTaskIdAiDescriptionPost,
  getListTasksApiV1CGuildIdTasksGetQueryKey,
  getReadTaskApiV1CGuildIdTasksTaskIdGetQueryKey,
  listTasksApiV1CGuildIdTasksGet,
  moveTaskApiV1CGuildIdTasksTaskIdMovePost,
  readTaskApiV1CGuildIdTasksTaskIdGet,
  reorderTasksApiV1CGuildIdTasksReorderPost,
  toggleChecklistItemApiV1CGuildIdTasksTaskIdChecklistItemIdPatch,
  updateTaskApiV1CGuildIdTasksTaskIdPatch,
} from "@/api/generated/tasks/tasks";
import { invalidate, q } from "@/api/query-keys";
import { useActiveGuildId } from "@/hooks/useActiveGuildId";
import { useGuildMutation } from "@/hooks/useApiMutation";
import { useAuth } from "@/hooks/useAuth";
import { toast } from "@/lib/chesterToast";
import { getErrorMessage } from "@/lib/errorMessage";
import { fetchAllPages } from "@/lib/fetchAllPages";
import { fireTaskCompletionFeedback } from "@/lib/taskCompletionFeedback";
import { statusForCategory } from "@/lib/taskStatusDefaults";
import type { MutationOpts } from "@/types/mutation";
import type { QueryOpts } from "@/types/query";

// ── Queries ─────────────────────────────────────────────────────────────────

// Returns the full ``TaskRead`` (the detail endpoint's shape) — a superset of
// the list row that additionally carries the ``creator`` summary the edit page
// renders. The list hooks stay on ``TaskListRead``.
export const useTask = (taskId: number | null, options?: QueryOpts<TaskRead>) => {
  const guildId = useActiveGuildId();
  const { enabled: userEnabled = true, ...rest } = options ?? {};
  return useQuery<TaskRead>({
    queryKey: getReadTaskApiV1CGuildIdTasksTaskIdGetQueryKey(guildId, taskId!),
    queryFn: () => readTaskApiV1CGuildIdTasksTaskIdGet(guildId, taskId!),
    enabled: taskId !== null && Number.isFinite(taskId) && userEnabled,
    ...rest,
  });
};

/** The complete task list for `params`: the one key and fetch every reader of it shares. */
export const tasksQuery = (guildId: number, params: ListTasksApiV1CGuildIdTasksGetParams) => ({
  queryKey: getListTasksApiV1CGuildIdTasksGetQueryKey(guildId, params),
  // page_size=0 walks the server's fetch-all windows for the complete set.
  queryFn: () => fetchAllPages(listTasksApiV1CGuildIdTasksGet, guildId, params),
});

export const useTasks = (
  params: ListTasksApiV1CGuildIdTasksGetParams,
  options?: QueryOpts<TaskListResponse>
) => {
  const guildId = useActiveGuildId();
  return useQuery<TaskListResponse>({ ...tasksQuery(guildId, params), ...options });
};

export const usePrefetchTasks = () => {
  const qc = useQueryClient();
  const guildId = useActiveGuildId();
  return (params: ListTasksApiV1CGuildIdTasksGetParams) =>
    qc.prefetchQuery({ ...tasksQuery(guildId, params), staleTime: 30_000 });
};

// ── Task Mutations ──────────────────────────────────────────────────────────

export const useCreateTask = (
  options?: MutationOpts<TaskRead, Parameters<typeof createTaskApiV1CGuildIdTasksPost>[1]>
) =>
  useGuildMutation<TaskRead, Parameters<typeof createTaskApiV1CGuildIdTasksPost>[1]>(
    {
      mutationFn: (guildId, data) => createTaskApiV1CGuildIdTasksPost(guildId, data),
      invalidate: () => invalidate(q.allTasks()),
      errorKey: "projects:tasks.createError",
    },
    options
  );

// Search the React Query cache for the latest known copy of a task. Checks
// the per-task cache first (populated when the edit page is open) and falls
// back to scanning every cached list response. Used to snapshot the previous
// task_status.category before a status-changing PATCH so the success path can
// detect "transitioned into done" and fire the visual-feedback effect.
const findCachedTask = (
  guildId: number,
  queryClient: ReturnType<typeof useQueryClient>,
  taskId: number
): TaskListRead | null => {
  const direct = queryClient.getQueryData<TaskListRead>(
    getReadTaskApiV1CGuildIdTasksTaskIdGetQueryKey(guildId, taskId)
  );
  if (direct?.task_status) return direct;

  const entries = queryClient.getQueriesData<TaskListResponse>({
    predicate: (query) => {
      const first = query.queryKey[0];
      return typeof first === "string" && first.startsWith(`/api/v1/c/${guildId}/tasks/`);
    },
  });
  for (const [, value] of entries) {
    const items = value?.items;
    if (!Array.isArray(items)) continue;
    const found = items.find((item) => item?.id === taskId);
    if (found?.task_status) return found;
  }
  return null;
};

export const useUpdateTask = (
  options?: MutationOpts<
    TaskRead,
    {
      taskId: number;
      data: Parameters<typeof updateTaskApiV1CGuildIdTasksTaskIdPatch>[2];
      /** Passthrough request options (e.g. AbortSignal). The guild is the
       * active route's guild (path param). For cross-guild updates from
       * personal surfaces use useUpdateTaskInGuild instead. */
      params?: Parameters<typeof updateTaskApiV1CGuildIdTasksTaskIdPatch>[3];
    }
  >,
  /** What a failure says. Defaults to the status-change wording, which is what
   *  most callers of this are doing. */
  errorKey = "tasks:errors.statusUpdate"
) => {
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};
  const queryClient = useQueryClient();
  const guildId = useActiveGuildId();
  const { user } = useAuth();

  return useMutation({
    ...rest,
    mutationFn: async ({
      taskId,
      data,
      params,
    }: {
      taskId: number;
      data: Parameters<typeof updateTaskApiV1CGuildIdTasksTaskIdPatch>[2];
      params?: Parameters<typeof updateTaskApiV1CGuildIdTasksTaskIdPatch>[3];
    }) => {
      return updateTaskApiV1CGuildIdTasksTaskIdPatch(guildId, taskId, data, params);
    },
    onMutate: ({ taskId }) => {
      // Snapshot the task's previous status category so onSuccess can detect
      // the non-done -> done transition that fires the celebratory effect.
      const cached = findCachedTask(guildId, queryClient, taskId);
      return { previousCategory: cached?.task_status?.category ?? null };
    },
    onSuccess: (...args) => {
      const [updated, vars, context] = args;
      void invalidate(q.allTasks(), q.task(vars.taskId));

      // Completion feedback: only when (a) the current user is signed in,
      // (b) the status actually transitioned non-done -> done. Audio +
      // haptic always fire on completion the user initiated; visual is
      // additionally gated on the user being assigned to the task.
      const previousCategory = (context as { previousCategory?: string | null } | undefined)
        ?.previousCategory;
      const newCategory = updated?.task_status?.category;
      const movedIntoDone = newCategory === "done" && previousCategory !== "done";
      if (movedIntoDone && user) {
        const isAssigned = updated.assignees?.some((assignee) => assignee.id === user.id) ?? false;
        fireTaskCompletionFeedback(user, { isAssigned });
      }

      onSuccess?.(...args);
    },
    onError: (...args) => {
      toast.error(getErrorMessage(args[0], errorKey));
      onError?.(...args);
    },
    onSettled,
  });
};

/**
 * Tick or untick a task from somewhere that is not its project — a document's
 * checkbox. Done is the project's done column; unticked is in progress, the
 * same move the My Tasks box makes. Which column that is belongs to the
 * project, so its columns are read at the moment of ticking.
 */
export const useSetTaskDone = () => {
  const { t } = useTranslation("tasks");
  const guildId = useActiveGuildId();
  const queryClient = useQueryClient();
  const [resolving, setResolving] = useState(false);
  const { mutateAsync, isPending } = useUpdateTask({
    onSuccess: () =>
      queryClient.invalidateQueries({
        queryKey: getReadSmartChipsApiV1CGuildIdSmartChipsGetQueryKey(guildId),
      }),
  });

  const setDone = useCallback(
    async (taskId: number, done: boolean) => {
      setResolving(true);
      let targetId: number | null = null;
      try {
        const task = await queryClient.fetchQuery({
          queryKey: getReadTaskApiV1CGuildIdTasksTaskIdGetQueryKey(guildId, taskId),
          queryFn: () => readTaskApiV1CGuildIdTasksTaskIdGet(guildId, taskId),
        });
        const statuses = await listTaskStatusesApiV1CGuildIdProjectsProjectIdTaskStatusesGet(
          guildId,
          task.project_id
        );
        targetId = statusForCategory(statuses, done ? "done" : "in_progress")?.id ?? null;
      } catch (error) {
        toast.error(getErrorMessage(error, "tasks:errors.statusUpdate"));
        return;
      } finally {
        setResolving(false);
      }
      if (targetId === null) {
        toast.error(t("errors.statusNoMatch"));
        return;
      }
      // A failed update is reported by the update itself.
      await mutateAsync({ taskId, data: { task_status_id: targetId } }).catch(() => undefined);
    },
    [guildId, mutateAsync, queryClient, t]
  );

  return { setDone, pending: resolving || isPending };
};

/**
 * Cross-guild task update for personal/My-Tasks surfaces. The task lives in its
 * OWN guild (per-guild task ids collide), so the guild is passed EXPLICITLY in
 * the mutation variables rather than read from the active route. This is a
 * separate endpoint call from {@link useUpdateTask}, which is guild-page bound.
 */
export const useUpdateTaskInGuild = (
  options?: MutationOpts<
    TaskRead,
    {
      guildId: number;
      taskId: number;
      data: Parameters<typeof updateTaskApiV1CGuildIdTasksTaskIdPatch>[2];
    }
  >
) => {
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};
  const queryClient = useQueryClient();
  const { user } = useAuth();

  return useMutation({
    ...rest,
    mutationFn: async ({
      guildId,
      taskId,
      data,
    }: {
      guildId: number;
      taskId: number;
      data: Parameters<typeof updateTaskApiV1CGuildIdTasksTaskIdPatch>[2];
    }) => {
      return updateTaskApiV1CGuildIdTasksTaskIdPatch(guildId, taskId, data);
    },
    onMutate: ({ guildId, taskId }) => {
      const cached = findCachedTask(guildId, queryClient, taskId);
      return { previousCategory: cached?.task_status?.category ?? null };
    },
    onSuccess: (...args) => {
      const [updated, vars, context] = args;
      void invalidate(q.allTasks(), q.task(vars.taskId));

      const previousCategory = (context as { previousCategory?: string | null } | undefined)
        ?.previousCategory;
      const newCategory = updated?.task_status?.category;
      const movedIntoDone = newCategory === "done" && previousCategory !== "done";
      if (movedIntoDone && user) {
        const isAssigned = updated.assignees?.some((assignee) => assignee.id === user.id) ?? false;
        fireTaskCompletionFeedback(user, { isAssigned });
      }

      onSuccess?.(...args);
    },
    onError: (...args) => {
      toast.error(getErrorMessage(args[0], "tasks:errors.statusUpdate"));
      onError?.(...args);
    },
    onSettled,
  });
};

export const useDeleteTask = (options?: MutationOpts<void, number>) =>
  useGuildMutation<void, number>(
    {
      mutationFn: (guildId, taskId) => deleteTaskApiV1CGuildIdTasksTaskIdDelete(guildId, taskId),
      invalidate: () => invalidate(q.allTasks()),
      errorKey: "projects:tasks.bulkDeleteError",
    },
    options
  );

export const useBulkDeleteTasks = (options?: MutationOpts<void, number[]>) =>
  useGuildMutation<void, number[]>(
    {
      mutationFn: async (guildId, taskIds) => {
        await Promise.all(
          taskIds.map((id) => deleteTaskApiV1CGuildIdTasksTaskIdDelete(guildId, id))
        );
      },
      invalidate: () => invalidate(q.allTasks()),
      errorKey: "projects:tasks.bulkDeleteError",
    },
    options
  );

export const useBulkUpdateTasks = (
  options?: MutationOpts<
    TaskRead[],
    { taskIds: number[]; changes: Parameters<typeof updateTaskApiV1CGuildIdTasksTaskIdPatch>[2] }
  >
) =>
  useGuildMutation<
    TaskRead[],
    { taskIds: number[]; changes: Parameters<typeof updateTaskApiV1CGuildIdTasksTaskIdPatch>[2] }
  >(
    {
      mutationFn: (guildId, { taskIds, changes }) =>
        Promise.all(
          taskIds.map((taskId) => updateTaskApiV1CGuildIdTasksTaskIdPatch(guildId, taskId, changes))
        ),
      invalidate: () => invalidate(q.allTasks()),
      errorKey: "projects:tasks.bulkUpdateError",
    },
    options
  );

export const useBulkArchiveTasks = (options?: MutationOpts<ArchiveResponse[], number[]>) =>
  useGuildMutation<ArchiveResponse[], number[]>(
    {
      mutationFn: (guildId, taskIds) =>
        Promise.all(
          taskIds.map((taskId) =>
            archiveEntityApiV1CGuildIdArchiveEntityTypeEntityIdPost(guildId, "task", taskId)
          )
        ),
      invalidate: () => invalidate(q.allTasks()),
      errorKey: "projects:tasks.archiveError",
    },
    options
  );

export const useMoveTask = (
  options?: MutationOpts<TaskRead, { taskId: number; targetProjectId: number }>
) =>
  useGuildMutation<TaskRead, { taskId: number; targetProjectId: number }>(
    {
      mutationFn: (guildId, { taskId, targetProjectId }) =>
        moveTaskApiV1CGuildIdTasksTaskIdMovePost(guildId, taskId, {
          target_project_id: targetProjectId,
        }),
      invalidate: () => invalidate(q.allTasks()),
      errorKey: "tasks:edit.moveError",
    },
    options
  );

export const useDuplicateTask = (options?: MutationOpts<TaskRead, number>) =>
  useGuildMutation<TaskRead, number>(
    {
      mutationFn: (guildId, taskId) =>
        duplicateTaskApiV1CGuildIdTasksTaskIdDuplicatePost(guildId, taskId),
      invalidate: () => invalidate(q.allTasks()),
      errorKey: "common:error",
    },
    options
  );

export const useReorderTasks = (options?: MutationOpts<TaskRead[], TaskReorderRequest>) => {
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};
  const queryClient = useQueryClient();
  const guildId = useActiveGuildId();
  const { user } = useAuth();

  return useMutation({
    ...rest,
    mutationFn: async (payload: TaskReorderRequest) => {
      return reorderTasksApiV1CGuildIdTasksReorderPost(
        guildId,
        payload as Parameters<typeof reorderTasksApiV1CGuildIdTasksReorderPost>[1]
      );
    },
    onMutate: (payload) => {
      // Detect non-done -> done transitions in this reorder by inspecting
      // only the payload items whose task_status_id actually changed. The
      // reorder response contains every reordered task in the project, so
      // checking each response item leads to false positives whenever a
      // task's cache state is missing or stale (e.g. an already-Done task
      // filtered out of the kanban view).
      //
      // Track two flags separately because audio + haptic fire on any
      // transition the user initiated, while visual additionally requires
      // the user to be assigned to the task.
      let didTransitionToDone = false;
      let assignedTransitionToDone = false;
      if (user) {
        for (const item of payload.items) {
          const cached = findCachedTask(guildId, queryClient, item.id);
          if (!cached) continue;
          if (cached.task_status_id === item.task_status_id) continue; // unchanged
          if (cached.task_status?.category === "done") continue; // already done
          const newStatus = queryClient
            .getQueryData<TaskStatusRead[]>(
              getListTaskStatusesApiV1CGuildIdProjectsProjectIdTaskStatusesGetQueryKey(
                guildId,
                cached.project_id
              )
            )
            ?.find((s) => s.id === item.task_status_id);
          if (newStatus?.category !== "done") continue; // not moving into done
          didTransitionToDone = true;
          const isAssigned = cached.assignees?.some((assignee) => assignee.id === user.id) ?? false;
          if (isAssigned) {
            assignedTransitionToDone = true;
            break; // any assignment guarantees both flags; no need to keep scanning
          }
        }
      }
      return { didTransitionToDone, assignedTransitionToDone };
    },
    onSuccess: (...args) => {
      const [, , context] = args;
      void invalidate(q.allTasks());

      const ctx = context as
        | { didTransitionToDone?: boolean; assignedTransitionToDone?: boolean }
        | undefined;
      if (ctx?.didTransitionToDone && user) {
        fireTaskCompletionFeedback(user, {
          isAssigned: ctx.assignedTransitionToDone ?? false,
        });
      }

      onSuccess?.(...args);
    },
    onError: onError,
    onSettled,
  });
};

export const useArchiveDoneTasks = (
  options?: MutationOpts<ArchiveDoneResponse, { projectId: number; taskStatusId?: number }>
) =>
  useGuildMutation<ArchiveDoneResponse, { projectId: number; taskStatusId?: number }>(
    {
      mutationFn: (guildId, { projectId, taskStatusId }) =>
        archiveDoneTasksApiV1CGuildIdTasksArchiveDonePost(guildId, {
          project_id: projectId,
          ...(taskStatusId !== undefined && { task_status_id: taskStatusId }),
        } as Parameters<typeof archiveDoneTasksApiV1CGuildIdTasksArchiveDonePost>[1]),
      invalidate: () => invalidate(q.allTasks()),
      errorKey: "projects:tasks.archiveError",
    },
    options
  );

export const useGenerateTaskDescription = (
  options?: MutationOpts<GenerateDescriptionResponse, number>
) =>
  useGuildMutation<GenerateDescriptionResponse, number>(
    {
      mutationFn: (guildId, taskId) =>
        generateTaskDescriptionApiV1CGuildIdTasksTaskIdAiDescriptionPost(guildId, taskId),
      errorKey: "tasks:edit.generateDescriptionError",
    },
    options
  );

// ── Checklist Mutations ─────────────────────────────────────────────────────

// Adding, renaming, reordering and deleting arrive as the whole list through
// ``useUpdateTask``. A tick is its own call: it names one item, so two people
// ticking different lines of the same task do not overwrite each other.
export const useToggleChecklistItem = (
  options?: MutationOpts<ChecklistItem[], { taskId: number; itemId: string; done: boolean }>
) =>
  useGuildMutation<ChecklistItem[], { taskId: number; itemId: string; done: boolean }>(
    {
      mutationFn: (guildId, { taskId, itemId, done }) =>
        toggleChecklistItemApiV1CGuildIdTasksTaskIdChecklistItemIdPatch(guildId, taskId, itemId, {
          done,
        }),
      invalidate: (_data, { taskId }) => {
        void invalidate(q.task(taskId), q.allTasks());
      },
      errorKey: "tasks:checklist.updateError",
    },
    options
  );

export const useGenerateChecklist = (options?: MutationOpts<GenerateChecklistResponse, number>) =>
  useGuildMutation<GenerateChecklistResponse, number>(
    {
      mutationFn: (guildId, taskId) =>
        generateTaskChecklistApiV1CGuildIdTasksTaskIdAiChecklistPost(guildId, taskId),
      errorKey: "tasks:checklist.generateError",
    },
    options
  );
