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
  const { creator: _creator, guild, project, assignees, ...rest } = task;
  return {
    ...rest,
    // The detail shape carries assignees as plain users, with no per-assignment
    // completion, so this projection cannot report one. Its only consumers are
    // the project task views, which never read it — do not reuse this for the
    // My Tasks focus list, which would read the null as "still mine to do".
    assignees: assignees.map((assignee) => ({ ...assignee, completed_at: null })),
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
