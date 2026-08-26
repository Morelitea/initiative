import type { FilterPresetRead, TaskFilterSpec } from "@/api/generated/initiativeAPI.schemas";

let counter = 0;

export function resetCounter(): void {
  counter = 0;
}

export function buildFilterPreset(overrides: Partial<FilterPresetRead> = {}): FilterPresetRead {
  counter++;
  return {
    id: counter,
    project_id: 1,
    slug: `preset-${counter}`,
    name: `Preset ${counter}`,
    position: counter - 1,
    is_default: false,
    filters: {} as TaskFilterSpec,
    created_at: "2026-01-15T00:00:00.000Z",
    updated_at: "2026-01-15T00:00:00.000Z",
    ...overrides,
  };
}

/** The four every project is seeded with, in order. */
export function buildDefaultFilterPresets(projectId = 1): FilterPresetRead[] {
  const seeded: Array<[string, string, TaskFilterSpec]> = [
    ["all", "All", {} as TaskFilterSpec],
    [
      "incomplete",
      "Incomplete",
      { status_categories: ["backlog", "todo", "in_progress"] } as TaskFilterSpec,
    ],
    ["unassigned", "Unassigned", { assignees: ["none"] } as TaskFilterSpec],
    ["mine", "Mine", { assignees: ["me"] } as TaskFilterSpec],
  ];
  return seeded.map(([slug, name, filters], index) =>
    buildFilterPreset({
      project_id: projectId,
      slug,
      name,
      filters,
      position: index,
      is_default: slug === "all",
    })
  );
}
