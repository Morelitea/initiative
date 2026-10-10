import type {
  TaskFilterSpec,
  ToolViewRead,
  ToolViewSetRead,
  ToolViewSetWrite,
  ViewLayoutType,
} from "@/api/generated/initiativeAPI.schemas";

let counter = 0;

export function resetCounter(): void {
  counter = 0;
}

export function buildToolView(overrides: Partial<ToolViewRead> = {}): ToolViewRead {
  counter++;
  return {
    id: counter,
    name: `View ${counter}`,
    slug: `view-${counter}`,
    position: counter - 1,
    is_default: false,
    definition: { layout: { type: "table" } },
    ...overrides,
  };
}

const SHIPPED: Array<[string, string, ViewLayoutType, TaskFilterSpec | null]> = [
  ["table", "Table", "table", null],
  ["board", "Board", "board", null],
  ["calendar", "Calendar", "calendar", null],
  ["incomplete", "Incomplete", "table", { status_categories: ["backlog", "todo", "in_progress"] }],
  ["unassigned", "Unassigned", "table", { assignees: ["none"] }],
  ["mine", "Mine", "table", { assignees: ["me"] }],
];

/** The views a project shows until it stores its own, as the server sends them. */
export function buildShippedProjectViews(): ToolViewRead[] {
  return SHIPPED.map(([slug, name, layout, filters], position) => ({
    id: null,
    name,
    slug,
    position,
    is_default: position === 0,
    definition: { layout: { type: layout }, filters },
  }));
}

export function buildToolViewSet(overrides: Partial<ToolViewSetRead> = {}): ToolViewSetRead {
  return {
    views: buildShippedProjectViews(),
    item_layouts: [],
    stored: false,
    can_configure: true,
    ...overrides,
  };
}

/** The set the server answers a save of `write` with: stored as sent, a new
 *  view named after its name. */
export function buildSavedViewSet(write: ToolViewSetWrite): ToolViewSetRead {
  return buildToolViewSet({
    stored: true,
    views: write.views.map((view, position) => ({
      id: position + 1,
      name: view.name,
      slug: view.slug ?? view.name.toLowerCase().replace(/[^a-z0-9]+/g, "-"),
      position,
      is_default: view.is_default ?? false,
      definition: view.definition,
    })),
  });
}
