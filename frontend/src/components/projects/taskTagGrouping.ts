import type { TagSummary, TaskListRead } from "@/api/generated/initiativeAPI.schemas";

/**
 * Column id of the hidden column that drives "group by tag" in the project
 * task table. The column never renders as a column of its own — the tags
 * column already shows a task's tags — it exists so the table has a single
 * value per row to group on.
 */
export const TAG_GROUP_COLUMN_ID = "tag group";

/**
 * A task row carrying the one tag it is grouped under. Undefined when the
 * table is not grouped by tag, so a plain task list is a valid row list.
 */
export type TaskTagRow = TaskListRead & { tagGroup?: string };

/**
 * One row per (task, tag) pair, so a task with three tags appears under each
 * of its three tags rather than in an arbitrary single group. Tasks without
 * tags get one row in the untagged group.
 */
export const fanOutTasksByTag = (tasks: TaskListRead[], untaggedLabel: string): TaskTagRow[] =>
  tasks.flatMap((task) => {
    const tags = task.tags ?? [];
    if (tags.length === 0) {
      return [{ ...task, tagGroup: untaggedLabel }];
    }
    return tags.map((tag) => ({ ...task, tagGroup: tag.name }));
  });

/**
 * Row id for a fanned-out row. A task occupies one row per tag, so the task id
 * alone is no longer unique across the table.
 */
export const tagRowId = (row: TaskTagRow): string =>
  row.tagGroup === undefined ? String(row.id) : `${row.id}::${row.tagGroup}`;

/**
 * Tags seen on the given tasks, keyed by name — the group value is a tag name,
 * and this maps it back to the tag so the group header can render its badge.
 */
export const collectTagsByName = (tasks: TaskListRead[]): Map<string, TagSummary> => {
  const byName = new Map<string, TagSummary>();
  for (const task of tasks) {
    for (const tag of task.tags ?? []) {
      if (!byName.has(tag.name)) {
        byName.set(tag.name, tag);
      }
    }
  }
  return byName;
};

/**
 * Collapse fanned-out rows back to the tasks they came from, preserving the
 * original task objects so consumers keep reference equality with the list.
 */
export const uniqueTasksFromRows = (
  rows: TaskTagRow[],
  tasksById: Map<number, TaskListRead>
): TaskListRead[] => {
  const seen = new Set<number>();
  const tasks: TaskListRead[] = [];
  for (const row of rows) {
    if (seen.has(row.id)) {
      continue;
    }
    seen.add(row.id);
    tasks.push(tasksById.get(row.id) ?? row);
  }
  return tasks;
};
