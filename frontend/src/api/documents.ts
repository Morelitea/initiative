import {
  autocompleteDocumentsApiV1DocumentsAutocompleteGet,
  getBacklinksApiV1DocumentsDocumentIdBacklinksGet,
} from "@/api/generated/documents/documents";

export interface DocumentAutocomplete {
  id: number;
  title: string;
  updated_at: string;
}

export interface DocumentBacklink {
  id: number;
  title: string;
  updated_at: string;
}

/**
 * Search documents by title within an initiative for autocomplete/wikilinks.
 * Returns lightweight document info (id, title, updated_at) for typeahead.
 */
export async function autocompleteDocuments(
  initiativeId: number,
  query: string,
  limit = 10
): Promise<DocumentAutocomplete[]> {
  return autocompleteDocumentsApiV1DocumentsAutocompleteGet({
    initiative_id: initiativeId,
    q: query,
    limit,
  }) as unknown as Promise<DocumentAutocomplete[]>;
}

/**
 * Get documents that link to the specified document (backlinks).
 */
export async function getDocumentBacklinks(documentId: number): Promise<DocumentBacklink[]> {
  return getBacklinksApiV1DocumentsDocumentIdBacklinksGet(documentId) as unknown as Promise<
    DocumentBacklink[]
  >;
}
