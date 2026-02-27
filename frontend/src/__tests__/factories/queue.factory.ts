import type {
  QueueRead,
  QueueSummary,
  QueueListResponse,
  QueueItemRead,
  QueuePermissionRead,
  QueueRolePermissionRead,
} from "@/api/generated/initiativeAPI.schemas";

let counter = 0;

export function resetCounter(): void {
  counter = 0;
}

export function buildQueueItem(overrides: Partial<QueueItemRead> = {}): QueueItemRead {
  counter++;
  return {
    id: counter,
    queue_id: 1,
    label: `Item ${counter}`,
    position: counter * 10,
    color: null,
    notes: null,
    is_visible: true,
    user_id: null,
    user: null,
    tags: [],
    documents: [],
    tasks: [],
    created_at: "2026-01-15T00:00:00.000Z",
    ...overrides,
  };
}

export function buildQueueSummary(overrides: Partial<QueueSummary> = {}): QueueSummary {
  counter++;
  return {
    id: counter,
    name: `Queue ${counter}`,
    description: null,
    initiative_id: 1,
    guild_id: 1,
    created_by_id: 1,
    current_round: 1,
    is_active: false,
    item_count: 0,
    created_at: "2026-01-15T00:00:00.000Z",
    updated_at: "2026-01-15T00:00:00.000Z",
    my_permission_level: "owner",
    ...overrides,
  };
}

export function buildQueue(overrides: Partial<QueueRead> = {}): QueueRead {
  counter++;
  return {
    id: counter,
    name: `Queue ${counter}`,
    description: null,
    initiative_id: 1,
    guild_id: 1,
    created_by_id: 1,
    current_round: 1,
    is_active: false,
    item_count: 0,
    created_at: "2026-01-15T00:00:00.000Z",
    updated_at: "2026-01-15T00:00:00.000Z",
    my_permission_level: "owner",
    items: [],
    current_item: null,
    permissions: [],
    role_permissions: [],
    ...overrides,
  };
}

export function buildQueueListResponse(
  itemsOrOverrides: QueueSummary[] | Partial<QueueListResponse> = {}
): QueueListResponse {
  if (Array.isArray(itemsOrOverrides)) {
    return {
      items: itemsOrOverrides,
      total_count: itemsOrOverrides.length,
      page: 1,
      page_size: 20,
      has_next: false,
    };
  }
  return {
    items: [],
    total_count: 0,
    page: 1,
    page_size: 20,
    has_next: false,
    ...itemsOrOverrides,
  };
}

export function buildQueuePermission(
  overrides: Partial<QueuePermissionRead> = {}
): QueuePermissionRead {
  return {
    user_id: 1,
    level: "owner",
    created_at: "2026-01-15T00:00:00.000Z",
    ...overrides,
  };
}

export function buildQueueRolePermission(
  overrides: Partial<QueueRolePermissionRead> = {}
): QueueRolePermissionRead {
  return {
    initiative_role_id: 1,
    role_name: "member",
    role_display_name: "Member",
    level: "read",
    created_at: "2026-01-15T00:00:00.000Z",
    ...overrides,
  };
}
