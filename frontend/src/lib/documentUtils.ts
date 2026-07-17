import { autocompleteDocumentsApiV1GGuildIdDocumentsAutocompleteGet } from "@/api/generated/documents/documents";

/**
 * Server's cap on the documents list `ids` filter (and its page_size ceiling).
 * Mirrors MAX_DOCUMENT_IDS in the backend's documents endpoint.
 */
export const MAX_DOCUMENT_IDS = 100;

export interface DocumentAutocomplete {
  id: number;
  title: string;
  updated_at: string;
}

/**
 * Search documents by title within an initiative for autocomplete/wikilinks.
 * Returns lightweight document info (id, title, updated_at) for typeahead.
 */
export async function autocompleteDocuments(
  guildId: number,
  initiativeId: number,
  query: string,
  limit = 10
): Promise<DocumentAutocomplete[]> {
  return autocompleteDocumentsApiV1GGuildIdDocumentsAutocompleteGet(guildId, {
    initiative_id: initiativeId,
    q: query,
    limit,
  }) as unknown as Promise<DocumentAutocomplete[]>;
}
