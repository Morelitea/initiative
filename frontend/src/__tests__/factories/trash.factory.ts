import type {
  TrashItem,
  TrashItemEntityType,
  TrashListResponse,
} from "@/api/generated/initiativeAPI.schemas";

let counter = 0;

export function resetCounter(): void {
  counter = 0;
}

export function buildTrashItem(overrides: Partial<TrashItem> = {}): TrashItem {
  counter++;
  return {
    entity_type: "task" as TrashItemEntityType,
    entity_id: counter,
    name: `Item ${counter}`,
    deleted_at: new Date(2026, 3, 20, 10, 0, 0).toISOString(),
    deleted_by_id: 1,
    deleted_by_display: "Test User",
    purge_at: new Date(2026, 6, 19, 10, 0, 0).toISOString(),
    ...overrides,
  };
}

export function buildTrashListResponse(
  items: TrashItem[] = [],
  overrides: Partial<TrashListResponse> = {}
): TrashListResponse {
  return {
    items,
    total: items.length,
    retention_days: 90,
    ...overrides,
  };
}
