import type { DocumentSummary } from "@/api/generated/initiativeAPI.schemas";

import { ownerCan } from "./can";

let counter = 0;

export function resetCounter(): void {
  counter = 0;
}

export function buildDocumentSummary(overrides: Partial<DocumentSummary> = {}): DocumentSummary {
  counter++;
  return {
    id: counter,
    guild_id: 1,
    initiative_id: 1,
    name: `Document ${counter}`,
    featured_image_url: null,
    is_template: false,
    created_by: 1,
    created_at: "2026-01-15T00:00:00.000Z",
    updated_at: "2026-01-15T00:00:00.000Z",
    initiative: null,
    owner: null,
    owner_app: null,
    projects: [],
    comment_count: 0,
    comments_enabled: true,
    grants: [],
    archived_at: null,
    can: ownerCan(),
    tags: [],
    properties: [],
    document_type: "native",
    file_url: null,
    file_content_type: null,
    file_size: null,
    original_filename: null,
    smart_link_url: null,
    yjs_updated_at: null,
    ...overrides,
  };
}
