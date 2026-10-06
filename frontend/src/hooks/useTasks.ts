import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useState } from "react";
import { useTranslation } from "react-i18next";

import { archiveEntity } from "@/api/generated/archive/archive";
import type {
  ArchiveDoneResponse,
  ArchiveResponse,
  ChecklistItem,
  GenerateChecklistResponse,
  GenerateDescriptionResponse,
  ListTasksParams,
  TaskListRead,
  TaskListResponse,
  TaskRead,
  TaskReorderRequest,
  TaskStatusCategory,
  TaskStatusRead,
  TaskUpdateScope,
} from "@/api/generated/initiativeAPI.schemas";
import { getReadSmartChipsQueryKey } from "@/api/generated/smart-chips/smart-chips";
import {
  getListTaskStatusesQueryKey,
  listTaskStatuses,
} from "@/api/generated/task-statuses/task-statuses";
import {
  archiveDoneTasks,
  createTask,
  deleteTask,
  duplicateTask,
  generateTaskChecklist,
  generateTaskDescription,
  getListTasksQueryKey,
  getReadTaskQueryKey,
  listTasks,
  moveTask,
  readTask,
  reorderTasks,
  skipTask,
  toggleChecklistItem,
  updateTask,
} from "@/api/generated/tasks/tasks";
import { invalidate, q } from "@/api/query-keys";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { useCommunityMutation } from "@/hooks/useApiMutation";
import { useAuth } from "@/hooks/useAuth";
import { getErrorMessage } from "@/lib/errorMessage";
import { fetchAllPages } from "@/lib/fetchAllPages";
import { toast } from "@/lib/mascotToast";
import { withZone } from "@/lib/recurrence";
import { fireTaskCompletionFeedback } from "@/lib/taskCompletionFeedback";
import { statusForCategory } from "@/lib/taskStatusDefaults";
import type { MutationOpts } from "@/types/mutation";
import type { QueryOpts } from "@/types/query";

// ── Queries ─────────────────────────────────────────────────────────────────

// Returns the full ``TaskRead`` (the detail endpoint's shape) — a superset of
// the list row that additionally carries the ``creator`` summary the edit page
// renders. The list hooks stay on ``TaskListRead``.
export const useTask = (taskId: number | null, options?: QueryOpts<TaskRead>) => {
  const communityId = useActiveCommunityId();
  const { enabled: userEnabled = true, ...rest } = options ?? {};
  return useQuery<TaskRead>({
    queryKey: getReadTaskQueryKey(communityId, taskId!),
    queryFn: () => readTask(communityId, taskId!),
    enabled: taskId !== null && Number.isFinite(taskId) && userEnabled,
    ...rest,
  });
};

/** The complete task list for `params`: the one key and fetch every reader of it shares. */
export const tasksQuery = (communityId: number, params: ListTasksParams) => ({
  queryKey: getListTasksQueryKey(communityId, params),
  // page_size=0 walks the server's fetch-all windows for the complete set.
  queryFn: () => fetchAllPages((p) => listTasks(communityId, p), params),
});

export const useTasks = (params: ListTasksParams, options?: QueryOpts<TaskListResponse>) => {
  const communityId = useActiveCommunityId();
  return useQuery<TaskListResponse>({ ...tasksQuery(communityId, params), ...options });
};

export const usePrefetchTasks = () => {
  const qc = useQueryClient();
  const communityId = useActiveCommunityId();
  return (params: ListTasksParams) =>
    qc.prefetchQuery({ ...tasksQuery(communityId, params), staleTime: 30_000 });
};

// ── Task Mutations ──────────────────────────────────────────────────────────

export const useCreateTask = (options?: MutationOpts<TaskRead, Parameters<typeof createTask>[1]>) =>
  useCommunityMutation<TaskRead, Parameters<typeof createTask>[1]>(
    {
      mutationFn: (communityId, data) => createTask(communityId, data),
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
  communityId: number,
  queryClient: ReturnType<typeof useQueryClient>,
  taskId: number
): TaskListRead | null => {
  const direct = queryClient.getQueryData<TaskListRead>(getReadTaskQueryKey(communityId, taskId));
  if (direct?.task_status) return direct;

  const entries = queryClient.getQueriesData<TaskListResponse>({
    predicate: (query) => {
      const first = query.queryKey[0];
      return typeof first === "string" && first.startsWith(`/api/v1/c/${communityId}/tasks/`);
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

/**
 * A status change the caller already shows as made. Passing it moves the
 * completion feedback from the response to the click, so it lands with the
 * tick rather than a round trip later.
 */
export interface OptimisticStatusChange {
  from: TaskStatusCategory;
  to: TaskStatusCategory;
}

export interface UpdateTaskVariables {
  taskId: number;
  data: Parameters<typeof updateTask>[2];
  /** Passthrough request options (e.g. AbortSignal). The community is the
   * active route's community (path param). For cross-community updates from
   * personal surfaces use useUpdateTaskInCommunity instead. */
  params?: Parameters<typeof updateTask>[3];
  statusChange?: OptimisticStatusChange;
}

export const useUpdateTask = (
  options?: MutationOpts<TaskRead, UpdateTaskVariables>,
  /** What a failure says. Defaults to the status-change wording, which is what
   *  most callers of this are doing. */
  errorKey = "tasks:errors.statusUpdate"
) => {
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};
  const queryClient = useQueryClient();
  const communityId = useActiveCommunityId();
  const { user } = useAuth();

  return useMutation({
    ...rest,
    mutationFn: async ({ taskId, data, params }: UpdateTaskVariables) => {
      return updateTask(communityId, taskId, withZone(data), params);
    },
    onMutate: ({ taskId, statusChange }) => {
      // Snapshot the task's previous status category so onSuccess can detect
      // the non-done -> done transition that fires the celebratory effect.
      const cached = findCachedTask(communityId, queryClient, taskId);
      if (!statusChange) {
        return { previousCategory: cached?.task_status?.category ?? null };
      }
      // The caller already shows the change, so the feedback goes with it.
      if (statusChange.to === "done" && statusChange.from !== "done" && user) {
        const isAssigned = cached?.assignees?.some((assignee) => assignee.id === user.id) ?? false;
        fireTaskCompletionFeedback(user, { isAssigned });
      }
      return { feedbackFired: true };
    },
    onSuccess: (...args) => {
      const [updated, vars, context] = args;
      void invalidate(q.allTasks(), q.task(vars.taskId));

      // Completion feedback: only when (a) the current user is signed in,
      // (b) the status actually transitioned non-done -> done. Audio +
      // haptic always fire on completion the user initiated; visual is
      // additionally gated on the user being assigned to the task.
      const ctx = context as
        | { previousCategory?: string | null; feedbackFired?: boolean }
        | undefined;
      const previousCategory = ctx?.previousCategory;
      const newCategory = updated?.task_status?.category;
      const movedIntoDone = newCategory === "done" && previousCategory !== "done";
      if (movedIntoDone && user && !ctx?.feedbackFired) {
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
 * Tick or untick a task from somewhere that is not its project — a file's
 * checkbox. Done is the project's done column; unticked is in progress, the
 * same move the My Tasks box makes. Which column that is belongs to the
 * project, so its columns are read at the moment of ticking.
 */
export const useSetTaskDone = () => {
  const { t } = useTranslation("tasks");
  const communityId = useActiveCommunityId();
  const queryClient = useQueryClient();
  const [resolving, setResolving] = useState(false);
  const { mutateAsync, isPending } = useUpdateTask({
    onSuccess: () =>
      queryClient.invalidateQueries({
        queryKey: getReadSmartChipsQueryKey(communityId),
      }),
  });

  const setDone = useCallback(
    async (taskId: number, done: boolean) => {
      setResolving(true);
      let targetId: number | null = null;
      try {
        const task = await queryClient.fetchQuery({
          queryKey: getReadTaskQueryKey(communityId, taskId),
          queryFn: () => readTask(communityId, taskId),
        });
        const statuses = await listTaskStatuses(communityId, task.project_id);
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
    [communityId, mutateAsync, queryClient, t]
  );

  return { setDone, pending: resolving || isPending };
};

/**
 * Cross-community task update for personal/My-Tasks surfaces. The task lives in its
 * OWN community (per-community task ids collide), so the community is passed EXPLICITLY in
 * the mutation variables rather than read from the active route. This is a
 * separate endpoint call from {@link useUpdateTask}, which is community-page bound.
 */
export const useUpdateTaskInCommunity = (
  options?: MutationOpts<
    TaskRead,
    {
      communityId: number;
      taskId: number;
      data: Parameters<typeof updateTask>[2];
    }
  >
) => {
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};
  const queryClient = useQueryClient();
  const { user } = useAuth();

  return useMutation({
    ...rest,
    mutationFn: async ({
      communityId,
      taskId,
      data,
    }: {
      communityId: number;
      taskId: number;
      data: Parameters<typeof updateTask>[2];
    }) => {
      return updateTask(communityId, taskId, withZone(data));
    },
    onMutate: ({ communityId, taskId }) => {
      const cached = findCachedTask(communityId, queryClient, taskId);
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

/** Which tasks of a repeating series a delete is for; `this` skips it. */
type DeleteTaskVariables = { taskId: number; scope?: TaskUpdateScope };

export const useDeleteTask = (options?: MutationOpts<void, DeleteTaskVariables>) =>
  useCommunityMutation<void, DeleteTaskVariables>(
    {
      mutationFn: (communityId, { taskId, scope }) =>
        deleteTask(communityId, taskId, scope ? { scope } : undefined),
      invalidate: () => invalidate(q.allTasks()),
      errorKey: "projects:tasks.bulkDeleteError",
    },
    options
  );

/** Move a repeating task on to its next occurrence without completing it. */
export const useSkipTask = (options?: MutationOpts<TaskRead, number>) =>
  useCommunityMutation<TaskRead, number>(
    {
      mutationFn: (communityId, taskId) => skipTask(communityId, taskId),
      invalidate: (_data, taskId) => invalidate(q.allTasks(), q.task(taskId)),
      errorKey: "tasks:edit.skipError",
    },
    options
  );

export const useBulkDeleteTasks = (options?: MutationOpts<void, number[]>) =>
  useCommunityMutation<void, number[]>(
    {
      mutationFn: async (communityId, taskIds) => {
        await Promise.all(taskIds.map((id) => deleteTask(communityId, id)));
      },
      invalidate: () => invalidate(q.allTasks()),
      errorKey: "projects:tasks.bulkDeleteError",
    },
    options
  );

export const useBulkUpdateTasks = (
  options?: MutationOpts<
    TaskRead[],
    { taskIds: number[]; changes: Parameters<typeof updateTask>[2] }
  >
) =>
  useCommunityMutation<
    TaskRead[],
    { taskIds: number[]; changes: Parameters<typeof updateTask>[2] }
  >(
    {
      mutationFn: (communityId, { taskIds, changes }) =>
        Promise.all(taskIds.map((taskId) => updateTask(communityId, taskId, withZone(changes)))),
      invalidate: () => invalidate(q.allTasks()),
      errorKey: "projects:tasks.bulkUpdateError",
    },
    options
  );

export const useBulkArchiveTasks = (options?: MutationOpts<ArchiveResponse[], number[]>) =>
  useCommunityMutation<ArchiveResponse[], number[]>(
    {
      mutationFn: (communityId, taskIds) =>
        Promise.all(taskIds.map((taskId) => archiveEntity(communityId, "task", taskId))),
      invalidate: () => invalidate(q.allTasks()),
      errorKey: "projects:tasks.archiveError",
    },
    options
  );

export const useMoveTask = (
  options?: MutationOpts<TaskRead, { taskId: number; targetProjectId: number }>
) =>
  useCommunityMutation<TaskRead, { taskId: number; targetProjectId: number }>(
    {
      mutationFn: (communityId, { taskId, targetProjectId }) =>
        moveTask(communityId, taskId, {
          target_project_id: targetProjectId,
        }),
      invalidate: () => invalidate(q.allTasks()),
      errorKey: "tasks:edit.moveError",
    },
    options
  );

export const useDuplicateTask = (options?: MutationOpts<TaskRead, number>) =>
  useCommunityMutation<TaskRead, number>(
    {
      mutationFn: (communityId, taskId) => duplicateTask(communityId, taskId),
      invalidate: () => invalidate(q.allTasks()),
      errorKey: "common:error",
    },
    options
  );

export const useReorderTasks = (options?: MutationOpts<TaskRead[], TaskReorderRequest>) => {
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};
  const queryClient = useQueryClient();
  const communityId = useActiveCommunityId();
  const { user } = useAuth();

  return useMutation({
    ...rest,
    mutationFn: async (payload: TaskReorderRequest) => {
      return reorderTasks(communityId, payload as Parameters<typeof reorderTasks>[1]);
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
          const cached = findCachedTask(communityId, queryClient, item.id);
          if (!cached) continue;
          if (cached.task_status_id === item.task_status_id) continue; // unchanged
          if (cached.task_status?.category === "done") continue; // already done
          const newStatus = queryClient
            .getQueryData<TaskStatusRead[]>(
              getListTaskStatusesQueryKey(communityId, cached.project_id)
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
  useCommunityMutation<ArchiveDoneResponse, { projectId: number; taskStatusId?: number }>(
    {
      mutationFn: (communityId, { projectId, taskStatusId }) =>
        archiveDoneTasks(communityId, {
          project_id: projectId,
          ...(taskStatusId !== undefined && { task_status_id: taskStatusId }),
        } as Parameters<typeof archiveDoneTasks>[1]),
      invalidate: () => invalidate(q.allTasks()),
      errorKey: "projects:tasks.archiveError",
    },
    options
  );

export const useGenerateTaskDescription = (
  options?: MutationOpts<GenerateDescriptionResponse, number>
) =>
  useCommunityMutation<GenerateDescriptionResponse, number>(
    {
      mutationFn: (communityId, taskId) => generateTaskDescription(communityId, taskId),
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
  useCommunityMutation<ChecklistItem[], { taskId: number; itemId: string; done: boolean }>(
    {
      mutationFn: (communityId, { taskId, itemId, done }) =>
        toggleChecklistItem(communityId, taskId, itemId, {
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
  useCommunityMutation<GenerateChecklistResponse, number>(
    {
      mutationFn: (communityId, taskId) => generateTaskChecklist(communityId, taskId),
      errorKey: "tasks:checklist.generateError",
    },
    options
  );
