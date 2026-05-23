import type { RecentItemRead } from "@/api/generated/initiativeAPI.schemas";

let counter = 0;

export function resetRecentCounter(): void {
  counter = 0;
}

/**
 * Build a generic recent-item for use in tests. Caller can override
 * ``entity_type`` and any other field. Use the type-specific helpers below
 * for ergonomic factories.
 */
export function buildRecentItem(overrides: Partial<RecentItemRead> = {}): RecentItemRead {
  counter++;
  return {
    entity_type: "project",
    entity_id: counter,
    guild_id: 1,
    name: `Recent Item ${counter}`,
    last_viewed_at: new Date().toISOString(),
    icon: null,
    document_type: null,
    mime_type: null,
    original_filename: null,
    ...overrides,
  };
}

export function buildRecentProjectItem(overrides: Partial<RecentItemRead> = {}): RecentItemRead {
  return buildRecentItem({ entity_type: "project", icon: "🛠", ...overrides });
}

export function buildRecentDocumentItem(overrides: Partial<RecentItemRead> = {}): RecentItemRead {
  return buildRecentItem({
    entity_type: "document",
    document_type: "native",
    ...overrides,
  });
}

export function buildRecentQueueItem(overrides: Partial<RecentItemRead> = {}): RecentItemRead {
  return buildRecentItem({ entity_type: "queue", ...overrides });
}

export function buildRecentCounterGroupItem(
  overrides: Partial<RecentItemRead> = {}
): RecentItemRead {
  return buildRecentItem({ entity_type: "counter_group", ...overrides });
}
