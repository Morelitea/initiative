import type {
  AutocompleteTasksApiV1GGuildIdTasksAutocompleteGetParams,
  TaskAutocomplete,
  TaskListRead,
  TaskRead,
} from "@/api/generated/initiativeAPI.schemas";
import { autocompleteTasksApiV1GGuildIdTasksAutocompleteGet } from "@/api/generated/tasks/tasks";

export type { TaskAutocomplete };

/**
 * Project the ``TaskRead`` detail shape onto the denormalized ``TaskListRead``
 * list row, deriving the list-only fields from the nested guild/project
 * summaries. Task mutation endpoints respond with ``TaskRead``, so surfaces
 * that hold list rows use this to apply a response without dropping the
 * denormalized fields.
 */
export const taskReadToListRow = (task: TaskRead): TaskListRead => {
  const { creator: _creator, guild, project, ...rest } = task;
  return {
    ...rest,
    guild_id: guild?.id ?? null,
    guild_name: guild?.name ?? null,
    project_name: project?.name ?? null,
    initiative_id: project?.initiative_id ?? null,
    initiative_name: project?.initiative?.name ?? null,
    initiative_color: project?.initiative?.color ?? null,
  };
};

/**
 * Search tasks by title for typeahead pickers.
 *
 * Returns lightweight task info (id, title) — it skips the eager-load chains
 * and annotation query the full task list endpoint runs, so a picker's cost
 * tracks what the user typed rather than the whole collection.
 */
export async function autocompleteTasks(
  guildId: number,
  params: AutocompleteTasksApiV1GGuildIdTasksAutocompleteGetParams
): Promise<TaskAutocomplete[]> {
  return autocompleteTasksApiV1GGuildIdTasksAutocompleteGet(guildId, {
    limit: 10,
    ...params,
  });
}
