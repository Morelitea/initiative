import type { PostRead } from "@/api/generated/initiativeAPI.schemas";

let counter = 0;

export function resetCounter(): void {
  counter = 0;
}

/**
 * The smallest valid Lexical editor state holding one paragraph — the shape
 * the composer actually saves, so a test post reads the way a real one does.
 */
export function buildLexicalBody(text: string): Record<string, unknown> {
  return {
    root: {
      type: "root",
      format: "",
      indent: 0,
      version: 1,
      direction: "ltr",
      children: [
        {
          type: "paragraph",
          format: "",
          indent: 0,
          version: 1,
          direction: "ltr",
          children: [
            {
              type: "text",
              text,
              format: 0,
              style: "",
              mode: "normal",
              detail: 0,
              version: 1,
            },
          ],
        },
      ],
    },
  };
}

export function buildPost(overrides: Partial<PostRead> = {}): PostRead {
  counter++;
  return {
    id: counter,
    name: `Post ${counter}`,
    body: buildLexicalBody(`Notice body ${counter}`),
    excerpt: `Notice body ${counter}`,
    initiative_id: 1,
    guild_id: 1,
    created_by: 1,
    created_at: "2026-01-15T00:00:00.000Z",
    updated_at: "2026-01-15T00:00:00.000Z",
    pinned_at: null,
    pinned_by: null,
    pin_expires_at: null,
    is_pinned: false,
    my_permission_level: "owner",
    comments_disabled: false,
    comment_count: 0,
    tags: [],
    grants: [],
    ...overrides,
  };
}
