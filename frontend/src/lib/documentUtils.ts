import { autocompleteDocumentsApiV1GGuildIdDocumentsAutocompleteGet } from "@/api/generated/documents/documents";
import type {
  AutocompleteDocumentsApiV1GGuildIdDocumentsAutocompleteGetParams,
  DocumentAutocomplete,
} from "@/api/generated/initiativeAPI.schemas";

/**
 * Server's cap on the documents list `ids` filter (and its page_size ceiling).
 * Mirrors MAX_DOCUMENT_IDS in the backend's documents endpoint.
 */
export const MAX_DOCUMENT_IDS = 100;

export type { DocumentAutocomplete };

/**
 * Search documents by title for typeahead pickers.
 *
 * Returns lightweight document info (id, title, updated_at, document_type).
 * Pass `initiative_id` to scope to one initiative, or omit it to search the
 * whole guild — templates are picked guild-wide.
 */
export async function autocompleteDocuments(
  guildId: number,
  params: AutocompleteDocumentsApiV1GGuildIdDocumentsAutocompleteGetParams
): Promise<DocumentAutocomplete[]> {
  return autocompleteDocumentsApiV1GGuildIdDocumentsAutocompleteGet(guildId, {
    limit: 10,
    ...params,
  }) as unknown as Promise<DocumentAutocomplete[]>;
}
