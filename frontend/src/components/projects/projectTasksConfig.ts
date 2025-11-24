import type { TaskPriority, TaskStatus } from "../../types/api";

export const taskStatusOrder: TaskStatus[] = ["backlog", "in_progress", "blocked", "done"];

export type DueFilterOption = "all" | "today" | "7_days" | "30_days" | "overdue";

export type UserOption = {
  id: number;
  label: string;
};

export const priorityVariant: Record<TaskPriority, "default" | "secondary" | "destructive"> = {
  low: "secondary",
  medium: "default",
  high: "default",
  urgent: "destructive",
};
