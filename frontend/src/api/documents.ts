import { apiClient } from "@/api/client";

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
  const response = await apiClient.get<DocumentAutocomplete[]>("/documents/autocomplete", {
    params: {
      initiative_id: initiativeId,
      q: query,
      limit,
    },
  });
  return response.data;
}

/**
 * Get documents that link to the specified document (backlinks).
 */
export async function getDocumentBacklinks(documentId: number): Promise<DocumentBacklink[]> {
  const response = await apiClient.get<DocumentBacklink[]>(`/documents/${documentId}/backlinks`);
  return response.data;
}
