import type { DocumentSummary } from "@/types/api";

let counter = 0;

export function resetCounter(): void {
  counter = 0;
}

export function buildDocumentSummary(
  overrides: Partial<DocumentSummary> = {},
): DocumentSummary {
  counter++;
  return {
    id: counter,
    initiative_id: 1,
    title: `Document ${counter}`,
    featured_image_url: null,
    is_template: false,
    created_by_id: 1,
    updated_by_id: 1,
    created_at: "2026-01-15T00:00:00.000Z",
    updated_at: "2026-01-15T00:00:00.000Z",
    initiative: null,
    projects: [],
    comment_count: 0,
    permissions: [],
    role_permissions: [],
    my_permission_level: "owner",
    tags: [],
    document_type: "native",
    file_url: null,
    file_content_type: null,
    file_size: null,
    original_filename: null,
    ...overrides,
  };
}
