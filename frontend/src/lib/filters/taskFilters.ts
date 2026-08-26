/**
 * The task filter vocabulary: one spec type, one way to compile it.
 *
 * `buildTaskConditions` is THE place filter values become the endpoint's DSL.
 * The tasks section, the route loader's prefetch, and the CSV export all call
 * it, so the three cannot disagree about what the list is showing — they used
 * to, and the loader's prefetch key silently never matched the component's.
 *
 * The spec mirrors `TaskFilterSpec` on the server (what a saved preset holds),
 * so preset, stored preference, and query params are all the same object.
 */

import type {
  TaskFilterSpec as ApiTaskFilterSpec,
  FilterCondition,
  FilterGroup,
  ListTasksApiV1GGuildIdTasksGetParams,
  TaskStatusCategory,
} from "@/api/generated/initiativeAPI.schemas";
import type { DueFilterOption } from "@/components/projects/projectTasksConfig";
import type { PropertyFilterCondition } from "@/components/properties/PropertyFilter";

export type TaskViewMode = "table" | "kanban" | "calendar";
export const TASK_VIEW_MODES = ["table", "kanban", "calendar"] as const;

/** The due-window tokens a preset can hold. `null` is "any due date". */
export type DueToken = Exclude<DueFilterOption, "all">;

/** The tokens `assignees` may hold besides a numeric user id. `me` is resolved
 *  per-request by the endpoint, which is what keeps a shared link portable. */
export const ASSIGNEE_ME = "me";
export const ASSIGNEE_NONE = "none";

export interface TaskFilterSpec {
  status_ids: number[];
  status_categories: TaskStatusCategory[];
  assignees: string[];
  tag_ids: number[];
  properties: PropertyFilterCondition[];
  due: DueToken | null;
  include_archived: boolean;
}

export const EMPTY_TASK_FILTERS: TaskFilterSpec = {
  status_ids: [],
  status_categories: [],
  assignees: [],
  tag_ids: [],
  properties: [],
  due: null,
  include_archived: false,
};

const DUE_TOKENS: readonly string[] = ["overdue", "today", "7_days", "30_days"];
const CATEGORIES: readonly string[] = ["backlog", "todo", "in_progress", "done"];

const numbers = (raw: unknown): number[] =>
  Array.isArray(raw) ? raw.filter((v): v is number => typeof v === "number") : [];

/** Coerce an API preset's `filters` (every key optional) into a full spec. */
export function specFromApi(raw: ApiTaskFilterSpec | null | undefined): TaskFilterSpec {
  if (!raw) return EMPTY_TASK_FILTERS;
  return {
    status_ids: numbers(raw.status_ids),
    status_categories: Array.isArray(raw.status_categories)
      ? raw.status_categories.filter((v): v is TaskStatusCategory => CATEGORIES.includes(v))
      : [],
    assignees: Array.isArray(raw.assignees)
      ? raw.assignees.filter((v): v is string => typeof v === "string")
      : [],
    tag_ids: numbers(raw.tag_ids),
    properties: Array.isArray(raw.properties)
      ? (raw.properties as PropertyFilterCondition[]).filter(
          (entry) => typeof entry?.property_id === "number"
        )
      : [],
    due: typeof raw.due === "string" && DUE_TOKENS.includes(raw.due) ? (raw.due as DueToken) : null,
    include_archived: raw.include_archived === true,
  };
}

/** The wire shape a preset is saved as. Identical keys — the spec IS the payload. */
export const specToApi = (spec: TaskFilterSpec): ApiTaskFilterSpec => ({
  status_ids: spec.status_ids,
  status_categories: spec.status_categories,
  assignees: spec.assignees,
  tag_ids: spec.tag_ids,
  properties: spec.properties as ApiTaskFilterSpec["properties"],
  due: spec.due,
  include_archived: spec.include_archived,
});

const sameIds = (a: readonly (number | string)[], b: readonly (number | string)[]) =>
  a.length === b.length && a.every((value, index) => value === b[index]);

export function taskFiltersEqual(a: TaskFilterSpec, b: TaskFilterSpec): boolean {
  return (
    sameIds(a.status_ids, b.status_ids) &&
    sameIds(a.status_categories, b.status_categories) &&
    sameIds(a.assignees, b.assignees) &&
    sameIds(a.tag_ids, b.tag_ids) &&
    a.due === b.due &&
    a.include_archived === b.include_archived &&
    JSON.stringify(a.properties) === JSON.stringify(b.properties)
  );
}

/** What the filter button badges. `include_archived` counts: widening what the
 *  list shows is as much a departure from the default as narrowing it. */
export function taskFilterCount(spec: TaskFilterSpec): number {
  return (
    spec.status_ids.length +
    spec.status_categories.length +
    spec.assignees.length +
    spec.tag_ids.length +
    spec.properties.length +
    (spec.due ? 1 : 0) +
    (spec.include_archived ? 1 : 0)
  );
}

// --- compiling to the wire DSL ---------------------------------------------

/** Today at local midnight, as an ISO instant.
 *
 *  Due windows are quantized to whole days rather than pinned to "now" so the
 *  compiled conditions are byte-identical for 24 hours. That is what lets the
 *  route loader's prefetch key match the component's query key — an
 *  instant-valued bound would change on every render and never hit. */
export function startOfLocalDay(offsetDays = 0): string {
  const date = new Date();
  date.setHours(0, 0, 0, 0);
  date.setDate(date.getDate() + offsetDays);
  return date.toISOString();
}

function dueConditions(due: DueToken): (FilterCondition | FilterGroup)[] {
  const between = (fromDays: number, toDays: number): FilterGroup => ({
    logic: "and",
    conditions: [
      { field: "due_date", op: "gte", value: startOfLocalDay(fromDays) },
      { field: "due_date", op: "lt", value: startOfLocalDay(toDays) },
    ],
  });
  switch (due) {
    case "overdue":
      return [{ field: "due_date", op: "lt", value: startOfLocalDay(0) }];
    case "today":
      return [between(0, 1)];
    case "7_days":
      return [between(0, 8)];
    case "30_days":
      return [between(0, 31)];
  }
}

function assigneeConditions(assignees: string[]): (FilterCondition | FilterGroup)[] {
  if (assignees.length === 0) return [];
  const wantsUnassigned = assignees.includes(ASSIGNEE_NONE);
  const ids = assignees.filter((value) => value !== ASSIGNEE_NONE);
  // No list of ids can express "nobody is on this", so it is its own operator.
  const unassigned: FilterCondition = { field: "assignee_ids", op: "is_null", value: true };
  const someone: FilterCondition = { field: "assignee_ids", op: "in_", value: ids };
  if (wantsUnassigned && ids.length === 0) return [unassigned];
  if (!wantsUnassigned) return [someone];
  return [{ logic: "or", conditions: [unassigned, someone] }];
}

/** Compile a spec into the endpoint's `conditions`. */
function statusConditions(spec: TaskFilterSpec): (FilterCondition | FilterGroup)[] {
  const byId: FilterCondition = {
    field: "task_status_id",
    op: "in_",
    value: spec.status_ids,
  };
  const byCategory: FilterCondition = {
    field: "status_category",
    op: "in_",
    value: spec.status_categories,
  };
  if (spec.status_ids.length === 0 && spec.status_categories.length === 0) return [];
  if (spec.status_categories.length === 0) return [byId];
  if (spec.status_ids.length === 0) return [byCategory];
  // One control, one question — "which statuses?" — answered either by naming
  // them or by naming a category. AND would make the two halves contradict
  // each other (a Blocked task is not in the Done category), so picking from
  // both sides has to widen the list, not empty it.
  return [{ logic: "or", conditions: [byId, byCategory] }];
}

export function buildTaskConditions(
  spec: TaskFilterSpec,
  options: { projectId: number }
): (FilterCondition | FilterGroup)[] {
  return [
    { field: "project_id", op: "eq", value: options.projectId },
    ...statusConditions(spec),
    ...assigneeConditions(spec.assignees),
    ...(spec.tag_ids.length > 0
      ? [{ field: "tag_ids", op: "in_" as const, value: spec.tag_ids }]
      : []),
    ...spec.properties.map((entry) => ({
      field: "property_values" as const,
      op: entry.op as FilterCondition["op"],
      value: { property_id: entry.property_id, value: entry.value },
    })),
    ...(spec.due ? dueConditions(spec.due) : []),
  ];
}

/**
 * The full list params, including archived. `include_archived` is a query
 * param rather than a condition, so it can't live in `conditions`.
 *
 * `page_size: 0` walks every page — the board and the drag-reorder need the
 * whole list, not a window.
 */
export function buildTaskListParams(
  spec: TaskFilterSpec,
  options: { projectId: number }
): ListTasksApiV1GGuildIdTasksGetParams {
  return {
    conditions: buildTaskConditions(spec, options),
    page_size: 0,
    ...(spec.include_archived && { include_archived: true }),
  };
}
