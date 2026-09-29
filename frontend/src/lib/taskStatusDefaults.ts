import type { IconName } from "lucide-react/dynamic";

import type { TaskStatusCategory, TaskStatusRead } from "@/api/generated/initiativeAPI.schemas";

export const TASK_STATUS_CATEGORY_DEFAULTS: Record<
  TaskStatusCategory,
  { color: string; icon: IconName }
> = {
  backlog: { color: "#94A3B8", icon: "circle-dashed" },
  todo: { color: "#94A3B8", icon: "circle" },
  in_progress: { color: "#60A5FA", icon: "circle-play" },
  done: { color: "#34D399", icon: "circle-check" },
};

export const defaultsForCategory = (category: TaskStatusCategory) =>
  TASK_STATUS_CATEGORY_DEFAULTS[category];

const equalsIgnoreCase = (a: string, b: string) => a.toLowerCase() === b.toLowerCase();

export const maybeSwapDefaultsOnCategoryChange = (
  previousCategory: TaskStatusCategory,
  nextCategory: TaskStatusCategory,
  currentColor: string,
  currentIcon: string
): { color: string; icon: IconName } => {
  const previousDefaults = TASK_STATUS_CATEGORY_DEFAULTS[previousCategory];
  const nextDefaults = TASK_STATUS_CATEGORY_DEFAULTS[nextCategory];
  return {
    color: equalsIgnoreCase(currentColor, previousDefaults.color)
      ? nextDefaults.color
      : currentColor,
    icon: currentIcon === previousDefaults.icon ? nextDefaults.icon : (currentIcon as IconName),
  };
};

/** Where a task lands when it is moved to a category its project may not have:
 *  the nearest one before it, so "done" in a project with no done column is
 *  the furthest the project goes. */
const CATEGORY_FALLBACK: Record<TaskStatusCategory, TaskStatusCategory[]> = {
  backlog: ["backlog"],
  todo: ["todo", "backlog"],
  in_progress: ["in_progress", "todo", "backlog"],
  done: ["done", "in_progress", "todo", "backlog"],
};

/** The status in `statuses` a task moved to `category` lands in, or `null`. */
export const statusForCategory = (
  statuses: TaskStatusRead[],
  category: TaskStatusCategory
): TaskStatusRead | null => {
  for (const candidate of CATEGORY_FALLBACK[category]) {
    const match = statuses.find((status) => status.category === candidate);
    if (match) return match;
  }
  return null;
};
