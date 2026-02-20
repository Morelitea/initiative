import { useQuery, useQueryClient, type UseQueryOptions } from "@tanstack/react-query";

import {
  readTaskApiV1TasksTaskIdGet,
  getReadTaskApiV1TasksTaskIdGetQueryKey,
  listTasksApiV1TasksGet,
  getListTasksApiV1TasksGetQueryKey,
  listSubtasksApiV1TasksTaskIdSubtasksGet,
  getListSubtasksApiV1TasksTaskIdSubtasksGetQueryKey,
} from "@/api/generated/tasks/tasks";
import type { Task } from "@/types/api";
import type {
  ListTasksApiV1TasksGetParams,
  TaskListResponse,
  SubtaskRead,
} from "@/api/generated/initiativeAPI.schemas";

type QueryOpts<T> = Omit<UseQueryOptions<T>, "queryKey" | "queryFn">;

// ── Queries ─────────────────────────────────────────────────────────────────

export const useTask = (taskId: number | null, options?: QueryOpts<Task>) => {
  const { enabled: userEnabled = true, ...rest } = options ?? {};
  return useQuery<Task>({
    queryKey: getReadTaskApiV1TasksTaskIdGetQueryKey(taskId!),
    queryFn: () => readTaskApiV1TasksTaskIdGet(taskId!) as unknown as Promise<Task>,
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
    queryFn: () => listTasksApiV1TasksGet(params) as unknown as Promise<TaskListResponse>,
    ...options,
  });
};

export const usePrefetchTasks = () => {
  const qc = useQueryClient();
  return (params: ListTasksApiV1TasksGetParams) => {
    return qc.prefetchQuery({
      queryKey: getListTasksApiV1TasksGetQueryKey(params),
      queryFn: () => listTasksApiV1TasksGet(params) as unknown as Promise<TaskListResponse>,
      staleTime: 30_000,
    });
  };
};

export const useSubtasks = (taskId: number, options?: QueryOpts<SubtaskRead[]>) => {
  return useQuery<SubtaskRead[]>({
    queryKey: getListSubtasksApiV1TasksTaskIdSubtasksGetQueryKey(taskId),
    queryFn: () =>
      listSubtasksApiV1TasksTaskIdSubtasksGet(taskId) as unknown as Promise<SubtaskRead[]>,
    ...options,
  });
};
