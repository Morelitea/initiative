import type { TagRead, TagSummary } from "@/api/generated/initiativeAPI.schemas";

let counter = 0;

export function resetCounter(): void {
  counter = 0;
}

const TAG_COLORS = [
  "#ef4444",
  "#f97316",
  "#eab308",
  "#22c55e",
  "#3b82f6",
  "#8b5cf6",
  "#ec4899",
  "#6b7280",
];

export function buildTagSummary(overrides: Partial<TagSummary> = {}): TagSummary {
  counter++;
  return {
    id: counter,
    name: `Tag ${counter}`,
    color: TAG_COLORS[(counter - 1) % TAG_COLORS.length],
    ...overrides,
  };
}

export function buildTag(overrides: Partial<TagRead> = {}): TagRead {
  counter++;
  return {
    id: counter,
    name: `Tag ${counter}`,
    color: TAG_COLORS[(counter - 1) % TAG_COLORS.length],
    guild_id: 1,
    created_at: "2026-01-15T00:00:00.000Z",
    updated_at: "2026-01-15T00:00:00.000Z",
    ...overrides,
  };
}
