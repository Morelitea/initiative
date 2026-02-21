import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import {
  readTaskApiV1TasksTaskIdGet,
  getReadTaskApiV1TasksTaskIdGetQueryKey,
  listTasksApiV1TasksGet,
  getListTasksApiV1TasksGetQueryKey,
  listSubtasksApiV1TasksTaskIdSubtasksGet,
  getListSubtasksApiV1TasksTaskIdSubtasksGetQueryKey,
  createTaskApiV1TasksPost,
  updateTaskApiV1TasksTaskIdPatch,
  deleteTaskApiV1TasksTaskIdDelete,
  moveTaskApiV1TasksTaskIdMovePost,
  duplicateTaskApiV1TasksTaskIdDuplicatePost,
  reorderTasksApiV1TasksReorderPost,
  archiveDoneTasksApiV1TasksArchiveDonePost,
  generateTaskDescriptionApiV1TasksTaskIdAiDescriptionPost,
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
import { getErrorMessage } from "@/lib/errorMessage";
import type {
  ArchiveDoneResponse,
  GenerateDescriptionResponse,
  GenerateSubtasksResponse,
  ListTasksApiV1TasksGetParams,
  SubtaskRead,
  SubtaskReorderItem,
  TaskListRead,
  TaskListResponse,
  TaskReorderRequest,
} from "@/api/generated/initiativeAPI.schemas";
import { castQueryFn } from "@/lib/query-utils";
import type { MutationOpts } from "@/types/mutation";
import type { QueryOpts } from "@/types/query";

// ── Queries ─────────────────────────────────────────────────────────────────

export const useTask = (taskId: number | null, options?: QueryOpts<TaskListRead>) => {
  const { enabled: userEnabled = true, ...rest } = options ?? {};
  return useQuery<TaskListRead>({
    queryKey: getReadTaskApiV1TasksTaskIdGetQueryKey(taskId!),
    queryFn: castQueryFn<TaskListRead>(() => readTaskApiV1TasksTaskIdGet(taskId!)),
    enabled: taskId !== null && Number.isFinite(taskId) && userEnabled,
    ...rest,
  });
};

export const useTasks = (
  params: ListTasksApiV1TasksGetParams,
  options?: QueryOpts<TaskListResponse>
) => {
  return useQuery<TaskListResponse>({
    queryKey: getListTasksApiV1TasksGetQueryKey(params),
    queryFn: castQueryFn<TaskListResponse>(() => listTasksApiV1TasksGet(params)),
    ...options,
  });
};

export const usePrefetchTasks = () => {
  const qc = useQueryClient();
  return (params: ListTasksApiV1TasksGetParams) => {
    return qc.prefetchQuery({
      queryKey: getListTasksApiV1TasksGetQueryKey(params),
      queryFn: castQueryFn<TaskListResponse>(() => listTasksApiV1TasksGet(params)),
      staleTime: 30_000,
    });
  };
};

export const useSubtasks = (taskId: number, options?: QueryOpts<SubtaskRead[]>) => {
  return useQuery<SubtaskRead[]>({
    queryKey: getListSubtasksApiV1TasksTaskIdSubtasksGetQueryKey(taskId),
    queryFn: castQueryFn<SubtaskRead[]>(() => listSubtasksApiV1TasksTaskIdSubtasksGet(taskId)),
    ...options,
  });
};

// ── Task Mutations ──────────────────────────────────────────────────────────

export const useCreateTask = (
  options?: MutationOpts<TaskListRead, Parameters<typeof createTaskApiV1TasksPost>[0]>
) => {
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async (data: Parameters<typeof createTaskApiV1TasksPost>[0]) => {
      return createTaskApiV1TasksPost(data) as unknown as Promise<TaskListRead>;
    },
    onSuccess: (...args) => {
      void invalidateAllTasks();
      onSuccess?.(...args);
    },
    onError: (...args) => {
      toast.error(getErrorMessage(args[0], "projects:tasks.createError"));
      onError?.(...args);
    },
    onSettled,
  });
};

export const useUpdateTask = (
  options?: MutationOpts<
    TaskListRead,
    {
      taskId: number;
      data: Parameters<typeof updateTaskApiV1TasksTaskIdPatch>[1];
      requestOptions?: Parameters<typeof updateTaskApiV1TasksTaskIdPatch>[2];
    }
  >
) => {
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async ({
      taskId,
      data,
      requestOptions,
    }: {
      taskId: number;
      data: Parameters<typeof updateTaskApiV1TasksTaskIdPatch>[1];
      requestOptions?: Parameters<typeof updateTaskApiV1TasksTaskIdPatch>[2];
    }) => {
      return updateTaskApiV1TasksTaskIdPatch(
        taskId,
        data,
        requestOptions
      ) as unknown as Promise<TaskListRead>;
    },
    onSuccess: (...args) => {
      void invalidateAllTasks();
      void invalidateTask(args[1].taskId);
      onSuccess?.(...args);
    },
    onError: (...args) => {
      toast.error(getErrorMessage(args[0], "tasks:errors.statusUpdate"));
      onError?.(...args);
    },
    onSettled,
  });
};

export const useDeleteTask = (options?: MutationOpts<void, number>) => {
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async (taskId: number) => {
      await deleteTaskApiV1TasksTaskIdDelete(taskId);
    },
    onSuccess: (...args) => {
      void invalidateAllTasks();
      onSuccess?.(...args);
    },
    onError: (...args) => {
      toast.error(getErrorMessage(args[0], "projects:tasks.bulkDeleteError"));
      onError?.(...args);
    },
    onSettled,
  });
};

export const useBulkDeleteTasks = (options?: MutationOpts<void, number[]>) => {
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async (taskIds: number[]) => {
      await Promise.all(taskIds.map((id) => deleteTaskApiV1TasksTaskIdDelete(id)));
    },
    onSuccess: (...args) => {
      void invalidateAllTasks();
      onSuccess?.(...args);
    },
    onError: (...args) => {
      toast.error(getErrorMessage(args[0], "projects:tasks.bulkDeleteError"));
      onError?.(...args);
    },
    onSettled,
  });
};

export const useBulkUpdateTasks = (
  options?: MutationOpts<
    TaskListRead[],
    { taskIds: number[]; changes: Parameters<typeof updateTaskApiV1TasksTaskIdPatch>[1] }
  >
) => {
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async ({
      taskIds,
      changes,
    }: {
      taskIds: number[];
      changes: Parameters<typeof updateTaskApiV1TasksTaskIdPatch>[1];
    }) => {
      const results = await Promise.all(
        taskIds.map(
          (taskId) =>
            updateTaskApiV1TasksTaskIdPatch(taskId, changes) as unknown as Promise<TaskListRead>
        )
      );
      return results;
    },
    onSuccess: (...args) => {
      void invalidateAllTasks();
      onSuccess?.(...args);
    },
    onError: (...args) => {
      toast.error(getErrorMessage(args[0], "projects:tasks.bulkUpdateError"));
      onError?.(...args);
    },
    onSettled,
  });
};

export const useBulkArchiveTasks = (options?: MutationOpts<TaskListRead[], number[]>) => {
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async (taskIds: number[]) => {
      const results = await Promise.all(
        taskIds.map(
          (taskId) =>
            updateTaskApiV1TasksTaskIdPatch(taskId, {
              is_archived: true,
            } as Parameters<
              typeof updateTaskApiV1TasksTaskIdPatch
            >[1]) as unknown as Promise<TaskListRead>
        )
      );
      return results;
    },
    onSuccess: (...args) => {
      void invalidateAllTasks();
      onSuccess?.(...args);
    },
    onError: (...args) => {
      toast.error(getErrorMessage(args[0], "projects:tasks.archiveError"));
      onError?.(...args);
    },
    onSettled,
  });
};

export const useMoveTask = (
  options?: MutationOpts<TaskListRead, { taskId: number; targetProjectId: number }>
) => {
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async ({
      taskId,
      targetProjectId,
    }: {
      taskId: number;
      targetProjectId: number;
    }) => {
      return moveTaskApiV1TasksTaskIdMovePost(taskId, {
        target_project_id: targetProjectId,
      }) as unknown as Promise<TaskListRead>;
    },
    onSuccess: (...args) => {
      void invalidateAllTasks();
      onSuccess?.(...args);
    },
    onError: (...args) => {
      toast.error(getErrorMessage(args[0], "tasks:edit.moveError"));
      onError?.(...args);
    },
    onSettled,
  });
};

export const useDuplicateTask = (options?: MutationOpts<TaskListRead, number>) => {
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async (taskId: number) => {
      return duplicateTaskApiV1TasksTaskIdDuplicatePost(taskId) as unknown as Promise<TaskListRead>;
    },
    onSuccess: (...args) => {
      void invalidateAllTasks();
      onSuccess?.(...args);
    },
    onError: (...args) => {
      toast.error(getErrorMessage(args[0], "common:error"));
      onError?.(...args);
    },
    onSettled,
  });
};

export const useReorderTasks = (options?: MutationOpts<TaskListRead[], TaskReorderRequest>) => {
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async (payload: TaskReorderRequest) => {
      return reorderTasksApiV1TasksReorderPost(
        payload as Parameters<typeof reorderTasksApiV1TasksReorderPost>[0]
      ) as unknown as Promise<TaskListRead[]>;
    },
    onSuccess: (...args) => {
      void invalidateAllTasks();
      onSuccess?.(...args);
    },
    onError: onError,
    onSettled,
  });
};

export const useArchiveDoneTasks = (
  options?: MutationOpts<ArchiveDoneResponse, { projectId: number; taskStatusId?: number }>
) => {
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async ({
      projectId,
      taskStatusId,
    }: {
      projectId: number;
      taskStatusId?: number;
    }) => {
      return archiveDoneTasksApiV1TasksArchiveDonePost({
        project_id: projectId,
        ...(taskStatusId !== undefined && { task_status_id: taskStatusId }),
      } as Parameters<
        typeof archiveDoneTasksApiV1TasksArchiveDonePost
      >[0]) as unknown as Promise<ArchiveDoneResponse>;
    },
    onSuccess: (...args) => {
      void invalidateAllTasks();
      onSuccess?.(...args);
    },
    onError: (...args) => {
      toast.error(getErrorMessage(args[0], "projects:tasks.archiveError"));
      onError?.(...args);
    },
    onSettled,
  });
};

export const useGenerateTaskDescription = (
  options?: MutationOpts<GenerateDescriptionResponse, number>
) => {
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async (taskId: number) => {
      return generateTaskDescriptionApiV1TasksTaskIdAiDescriptionPost(
        taskId
      ) as unknown as Promise<GenerateDescriptionResponse>;
    },
    onSuccess: (...args) => {
      onSuccess?.(...args);
    },
    onError: (...args) => {
      toast.error(getErrorMessage(args[0], "tasks:edit.generateDescriptionError"));
      onError?.(...args);
    },
    onSettled,
  });
};

// ── Subtask Mutations ───────────────────────────────────────────────────────

const invalidateSubtaskRelated = (taskId: number) => {
  void invalidateTaskSubtasks(taskId);
  void invalidateTask(taskId);
  void invalidateAllTasks();
};

export const useCreateSubtask = (
  options?: MutationOpts<SubtaskRead, { taskId: number; content: string }>
) => {
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async ({ taskId, content }: { taskId: number; content: string }) => {
      return createSubtaskApiV1TasksTaskIdSubtasksPost(taskId, {
        content,
      }) as unknown as Promise<SubtaskRead>;
    },
    onSuccess: (...args) => {
      invalidateSubtaskRelated(args[1].taskId);
      onSuccess?.(...args);
    },
    onError: (...args) => {
      toast.error(getErrorMessage(args[0], "tasks:checklist.addError"));
      onError?.(...args);
    },
    onSettled,
  });
};

export const useCreateSubtasksBatch = (
  options?: MutationOpts<SubtaskRead[], { taskId: number; contents: string[] }>
) => {
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async ({ taskId, contents }: { taskId: number; contents: string[] }) => {
      return createSubtasksBatchApiV1TasksTaskIdSubtasksBatchPost(taskId, {
        contents,
      }) as unknown as Promise<SubtaskRead[]>;
    },
    onSuccess: (...args) => {
      invalidateSubtaskRelated(args[1].taskId);
      onSuccess?.(...args);
    },
    onError: (...args) => {
      toast.error(getErrorMessage(args[0], "tasks:checklist.addError"));
      onError?.(...args);
    },
    onSettled,
  });
};

export const useUpdateSubtask = (
  options?: MutationOpts<
    SubtaskRead,
    {
      subtaskId: number;
      taskId: number;
      data: Parameters<typeof updateSubtaskApiV1SubtasksSubtaskIdPatch>[1];
    }
  >
) => {
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async ({
      subtaskId,
      data,
    }: {
      subtaskId: number;
      taskId: number;
      data: Parameters<typeof updateSubtaskApiV1SubtasksSubtaskIdPatch>[1];
    }) => {
      return updateSubtaskApiV1SubtasksSubtaskIdPatch(
        subtaskId,
        data
      ) as unknown as Promise<SubtaskRead>;
    },
    onSuccess: (...args) => {
      invalidateSubtaskRelated(args[1].taskId);
      onSuccess?.(...args);
    },
    onError: (...args) => {
      toast.error(getErrorMessage(args[0], "tasks:checklist.updateError"));
      onError?.(...args);
    },
    onSettled,
  });
};

export const useDeleteSubtask = (
  options?: MutationOpts<void, { subtaskId: number; taskId: number }>
) => {
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async ({ subtaskId }: { subtaskId: number; taskId: number }) => {
      await deleteSubtaskApiV1SubtasksSubtaskIdDelete(subtaskId);
    },
    onSuccess: (...args) => {
      invalidateSubtaskRelated(args[1].taskId);
      onSuccess?.(...args);
    },
    onError: (...args) => {
      toast.error(getErrorMessage(args[0], "tasks:checklist.deleteError"));
      onError?.(...args);
    },
    onSettled,
  });
};

export const useReorderSubtasks = (
  options?: MutationOpts<SubtaskRead[], { taskId: number; items: SubtaskReorderItem[] }>
) => {
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async ({ taskId, items }: { taskId: number; items: SubtaskReorderItem[] }) => {
      return reorderSubtasksApiV1TasksTaskIdSubtasksOrderPut(taskId, {
        items,
      }) as unknown as Promise<SubtaskRead[]>;
    },
    onSuccess: (...args) => {
      invalidateSubtaskRelated(args[1].taskId);
      onSuccess?.(...args);
    },
    onError: (...args) => {
      toast.error(getErrorMessage(args[0], "tasks:checklist.reorderError"));
      onError?.(...args);
    },
    onSettled,
  });
};

export const useGenerateSubtasks = (options?: MutationOpts<GenerateSubtasksResponse, number>) => {
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async (taskId: number) => {
      return generateTaskSubtasksApiV1TasksTaskIdAiSubtasksPost(
        taskId
      ) as unknown as Promise<GenerateSubtasksResponse>;
    },
    onSuccess: (...args) => {
      onSuccess?.(...args);
    },
    onError: (...args) => {
      toast.error(getErrorMessage(args[0], "tasks:checklist.generateError"));
      onError?.(...args);
    },
    onSettled,
  });
};
