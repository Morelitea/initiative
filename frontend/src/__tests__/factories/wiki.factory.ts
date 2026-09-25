import {
  WikiPageKind,
  WikiPageOrder,
  type WikiPageRead,
  type WikiRead,
  WikiReadingWidth,
} from "@/api/generated/initiativeAPI.schemas";

import { ownerCan } from "./can";

let counter = 0;

export function resetCounter(): void {
  counter = 0;
}

export function buildWiki(overrides: Partial<WikiRead> = {}): WikiRead {
  counter++;
  return {
    id: counter,
    name: `Wiki ${counter}`,
    description: null,
    initiative_id: 1,
    guild_id: 1,
    created_by: 1,
    created_at: "2026-01-15T00:00:00.000Z",
    updated_at: "2026-01-15T00:00:00.000Z",
    archived_at: null,
    page_count: 0,
    home_page_id: null,
    page_order: WikiPageOrder.manual,
    contents_depth: 2,
    show_connections: true,
    show_updated_at: true,
    reading_width: WikiReadingWidth.comfortable,
    accent_color: null,
    template_page_id: null,
    can: ownerCan(),
    comments_enabled: true,
    comment_count: 0,
    tags: [],
    grants: [],
    ...overrides,
  };
}

export function buildWikiPage(overrides: Partial<WikiPageRead> = {}): WikiPageRead {
  counter++;
  return {
    id: counter,
    wiki_id: 1,
    guild_id: 1,
    kind: WikiPageKind.page,
    parent_page_id: null,
    position: counter * 10,
    is_draft: false,
    title: `Page ${counter}`,
    slug: `page-${counter}`,
    created_by: 1,
    created_at: "2026-01-15T00:00:00.000Z",
    updated_at: "2026-01-15T00:00:00.000Z",
    headings: [],
    tags: [],
    content: {},
    comment_count: 0,
    ...overrides,
  };
}
