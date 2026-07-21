import type {
  AutocompleteTasksApiV1GGuildIdTasksAutocompleteGetParams,
  TaskAutocomplete,
} from "@/api/generated/initiativeAPI.schemas";
import { autocompleteTasksApiV1GGuildIdTasksAutocompleteGet } from "@/api/generated/tasks/tasks";

export type { TaskAutocomplete };

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
  }) as unknown as Promise<TaskAutocomplete[]>;
}
