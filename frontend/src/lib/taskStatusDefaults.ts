import type { IconName } from "lucide-react/dynamic";

import type { TaskStatusCategory } from "@/api/generated/initiativeAPI.schemas";

export const TASK_STATUS_CATEGORY_DEFAULTS: Record<
  TaskStatusCategory,
  { color: string; icon: IconName }
> = {
  backlog: { color: "#94A3B8", icon: "circle-dashed" },
  todo: { color: "#FBBF24", icon: "circle-pause" },
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
