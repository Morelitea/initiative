/**
 * The filter half of a data view.
 *
 * A binding's `conditions` are the app's own filter DSL — the same one the
 * tasks endpoint parses, under the viewer's own session. They have been
 * accepted and stored since dashboards shipped; what has never existed is a way
 * to *author* one or to *read* one back, which is why every task-backed widget
 * shows every task in the initiative.
 *
 * Two things live here and nowhere else:
 *
 * 1. **The field catalog** — which fields a dashboard may filter on, what kind
 *    of value each takes, and which operators apply. It is a subset of what the
 *    endpoint accepts (every `Task` column plus four virtual fields), chosen
 *    for what makes sense on a dashboard rather than mirroring the whole model.
 * 2. **Relative dates.** The DSL's values are literals, so a stored
 *    `due_date < 2026-09-30` is stale the day after someone saves it — useless
 *    on a dashboard, which is a standing question rather than a snapshot. A
 *    value may instead be `{relative: "+30d"}`, kept relative in the definition
 *    and expanded to an absolute instant by {@link expandConditions} on the way
 *    to the wire. The server never sees the relative form and needs no
 *    knowledge of it.
 *
 * Nothing here validates: the endpoint's own parser owns its limits (50
 * conditions, group depth 3), and re-stating them would mean maintaining them
 * twice. This drops what it cannot read and passes the rest through.
 */

/** Operators the endpoint's DSL understands (`app.schemas.query.FilterOp`).
 *  Negation is a flag on the condition, not a separate operator. */
export const FILTER_OPS = ["eq", "lt", "lte", "gt", "gte", "in_", "ilike", "is_null"] as const;
export type FilterOp = (typeof FILTER_OPS)[number];

/** A date expressed as an offset from "now", in days. Resolved at fetch time so
 *  a saved dashboard keeps asking the same *question* as the days pass. */
export interface RelativeDate {
  relative: number;
}

export type ConditionValue = string | number | boolean | null | (string | number)[] | RelativeDate;

export interface FilterLeaf {
  field: string;
  op: FilterOp;
  value?: ConditionValue;
  negate?: boolean;
}

export interface FilterGroup {
  logic: "and" | "or";
  conditions: FilterNode[];
}

export type FilterNode = FilterLeaf | FilterGroup;

export const isGroup = (node: FilterNode): node is FilterGroup =>
  typeof node === "object" && node !== null && Array.isArray((node as FilterGroup).conditions);

export const isRelativeDate = (value: unknown): value is RelativeDate =>
  typeof value === "object" &&
  value !== null &&
  typeof (value as RelativeDate).relative === "number";

// --- the field catalog ------------------------------------------------------

/** How a value is chosen, and therefore how it is rendered back. */
export type FieldKind =
  | "status_category"
  | "task_status"
  | "priority"
  | "member"
  | "tag"
  | "project"
  | "date"
  | "boolean"
  | "text";

export interface FilterFieldSpec {
  field: string;
  kind: FieldKind;
  ops: readonly FilterOp[];
  /** Whether the control picks several values at once. */
  multiple?: boolean;
}

/**
 * What a dashboard may filter tasks by.
 *
 * `assignee_ids`, `tag_ids`, and `status_category` are the endpoint's virtual
 * fields; the rest are `Task` columns. `initiative_ids` is deliberately absent —
 * a dashboard reads its own initiative and a binding cannot say otherwise.
 */
export const TASK_FILTER_FIELDS: readonly FilterFieldSpec[] = [
  { field: "status_category", kind: "status_category", ops: ["in_"], multiple: true },
  { field: "task_status_id", kind: "task_status", ops: ["in_"], multiple: true },
  { field: "priority", kind: "priority", ops: ["in_"], multiple: true },
  { field: "assignee_ids", kind: "member", ops: ["in_"], multiple: true },
  { field: "tag_ids", kind: "tag", ops: ["in_"], multiple: true },
  { field: "project_id", kind: "project", ops: ["eq"] },
  { field: "due_date", kind: "date", ops: ["lt", "lte", "gt", "gte", "is_null"] },
  { field: "start_date", kind: "date", ops: ["lt", "lte", "gt", "gte", "is_null"] },
  { field: "completed_at", kind: "date", ops: ["lt", "lte", "gt", "gte", "is_null"] },
  { field: "created_at", kind: "date", ops: ["lt", "lte", "gt", "gte"] },
  { field: "is_archived", kind: "boolean", ops: ["eq"] },
  { field: "title", kind: "text", ops: ["ilike"] },
] as const;

export const fieldSpec = (field: string): FilterFieldSpec | undefined =>
  TASK_FILTER_FIELDS.find((candidate) => candidate.field === field);

// --- reading ----------------------------------------------------------------

const readValue = (raw: unknown): ConditionValue | undefined => {
  if (raw === null) return null;
  if (isRelativeDate(raw)) return { relative: raw.relative };
  if (Array.isArray(raw)) {
    return raw.filter(
      (entry): entry is string | number => typeof entry === "string" || typeof entry === "number"
    );
  }
  if (typeof raw === "string" || typeof raw === "number" || typeof raw === "boolean") return raw;
  return undefined;
};

const readNode = (raw: unknown, depth: number): FilterNode | undefined => {
  if (typeof raw !== "object" || raw === null) return undefined;
  const record = raw as Record<string, unknown>;

  if (Array.isArray(record.conditions)) {
    // The endpoint caps group nesting; a definition deeper than that would 400
    // the whole query, so an over-deep group is dropped rather than sent.
    if (depth >= 1) return undefined;
    const children = record.conditions
      .map((child) => readNode(child, depth + 1))
      .filter((child): child is FilterNode => Boolean(child));
    if (!children.length) return undefined;
    return { logic: record.logic === "or" ? "or" : "and", conditions: children };
  }

  if (typeof record.field !== "string") return undefined;
  const op = FILTER_OPS.includes(record.op as FilterOp) ? (record.op as FilterOp) : undefined;
  if (!op) return undefined;
  const value = readValue(record.value);
  return {
    field: record.field,
    op,
    ...(value === undefined ? {} : { value }),
    ...(record.negate === true ? { negate: true } : {}),
  };
};

/** A stored `conditions` value as a typed list. Tolerates the single-group form
 *  a definition may carry, and drops anything unreadable. */
export const readConditions = (raw: unknown): FilterNode[] => {
  if (Array.isArray(raw)) {
    return raw.map((node) => readNode(node, 0)).filter((node): node is FilterNode => Boolean(node));
  }
  const single = readNode(raw, 0);
  return single ? [single] : [];
};

/** How many comparisons a filter makes, counted through groups — the number the
 *  provenance line shows. */
export const countLeaves = (nodes: FilterNode[]): number =>
  nodes.reduce((total, node) => total + (isGroup(node) ? countLeaves(node.conditions) : 1), 0);

// --- writing ----------------------------------------------------------------

const DAY = 86_400_000;

/**
 * Resolve relative dates against a given instant.
 *
 * Called on the way to the wire, never on the way to storage: the definition
 * keeps `{relative: 30}` so the question stays "due within 30 days", and the
 * endpoint receives the instant that means today.
 */
export const expandConditions = (nodes: FilterNode[], now: number): FilterNode[] =>
  nodes.map((node) => {
    if (isGroup(node)) {
      return { ...node, conditions: expandConditions(node.conditions, now) };
    }
    if (!isRelativeDate(node.value)) return node;
    return { ...node, value: new Date(now + node.value.relative * DAY).toISOString() };
  });
