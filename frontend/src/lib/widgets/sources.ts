/**
 * What each binding source *is* — the one description of a data view.
 *
 * The backend deliberately does not declare binding parameters: they belong to
 * the fetcher that consumes them, and mirroring them server-side would mean
 * maintaining every parameter twice. That is right for *validation*, and it
 * leaves a gap this module fills — nothing described a binding, so nothing
 * could describe one to a reader either. A tile could not say what it showed,
 * and the config dialog hand-wrote a branch per source to draw its controls.
 *
 * So this is a *description*, not a second validator. A stored definition is
 * still normalized by the server on save, and a binding that disagrees with
 * anything here is still whatever the server says it is. What the registry buys
 * is that four surfaces stop restating the same knowledge:
 *
 * - `unboundSlots()` — which ids a binding still needs (derived from `required`)
 * - the provenance line and popover on every tile
 * - the config dialog's controls
 * - the empty-state copy, which needs the row noun to say "no tasks match"
 *
 * It stays plain data plus pure functions. Resolving an id to a name is
 * deliberately *not* here: that is a fetch, it belongs to the viewer's own
 * session, and what it may say is an access question (see `provenance.ts`).
 */

import type { WidgetBinding } from "@/hooks/useWidgetData";
import type { WidgetSource } from "@/lib/widgets/dataShapes";

/** An entity a binding can point at. The kind decides which of the canvas's
 *  already-cached list queries resolves it to a name — never a fetch of its
 *  own, so a dense canvas costs no extra requests. */
export type EntityKind = "project" | "counter_group" | "counter" | "calendar" | "document";

interface BaseParam {
  /** The binding key this parameter reads and writes. */
  key: keyof WidgetBinding;
  /** Whether a binding is unusable until this is filled. Drives
   *  {@link unboundSlots}; a listing may ship a widget with the slot empty. */
  required?: boolean;
}

/** An id pointing at another resource in this initiative. */
export interface EntityParam extends BaseParam {
  kind: "entity";
  entity: EntityKind;
  /** Only offered once this other parameter has a value — a counter is chosen
   *  inside a group. */
  within?: keyof WidgetBinding;
}

/** A fixed vocabulary the app owns (as distinct from a widget's own display
 *  options, which the widget names in its `meta`). */
export interface EnumParam extends BaseParam {
  kind: "enum";
  values: readonly string[];
  fallback: string;
}

/** Free text the source parses — a sheet name, an A1 range. */
export interface TextParam extends BaseParam {
  kind: "text";
  placeholder?: string;
}

/** The filter DSL. One per source at most; the builder owns its own shape. */
export interface FilterParam extends BaseParam {
  kind: "filters";
}

/** A look-back/look-ahead in days. */
export interface WindowParam extends BaseParam {
  kind: "window";
  fallback: number;
}

export type SourceParam = EntityParam | EnumParam | TextParam | FilterParam | WindowParam;

export interface SourceDescriptor {
  /** Singular noun for one row, for counts and empty states ("no *tasks*
   *  match"). Rendered through i18n plurals, never concatenated. */
  rowNoun: "task" | "project" | "event" | "counter" | "cell" | "row";
  params: readonly SourceParam[];
}

/** Count buckets the `task_counts` source understands. Only `day` has a
 *  calendar shape, which is what a heatmap needs. */
/** Which of a task's dates a day-bucketed count places it on. Completion is
 *  the historical record, creation is intake, due is the plan — three genuinely
 *  different questions, and until now only the first was reachable. */
export const DAY_FIELDS = ["completed", "created", "due"] as const;

export const COUNT_BUCKETS = [
  "status_category",
  "status",
  "priority",
  "project",
  "assignee",
  "day",
] as const;

export const DEFAULT_WINDOW_DAYS = 90;

export const SOURCES: Record<WidgetSource, SourceDescriptor> = {
  tasks: {
    rowNoun: "task",
    params: [
      { kind: "entity", key: "project_id", entity: "project" },
      { kind: "filters", key: "conditions" },
    ],
  },
  task_counts: {
    rowNoun: "task",
    params: [
      { kind: "entity", key: "project_id", entity: "project" },
      { kind: "enum", key: "bucket", values: COUNT_BUCKETS, fallback: "status_category" },
      { kind: "enum", key: "day_field", values: DAY_FIELDS, fallback: "completed" },
      { kind: "filters", key: "conditions" },
    ],
  },
  projects: {
    rowNoun: "project",
    params: [{ kind: "filters", key: "conditions" }],
  },
  calendar_entries: {
    rowNoun: "event",
    params: [
      { kind: "entity", key: "calendar_id", entity: "calendar" },
      { kind: "window", key: "window_days", fallback: DEFAULT_WINDOW_DAYS },
    ],
  },
  counter: {
    rowNoun: "counter",
    params: [
      { kind: "entity", key: "counter_group_id", entity: "counter_group", required: true },
      {
        kind: "entity",
        key: "counter_id",
        entity: "counter",
        within: "counter_group_id",
        required: true,
      },
    ],
  },
  counter_group: {
    rowNoun: "counter",
    params: [{ kind: "entity", key: "counter_group_id", entity: "counter_group", required: true }],
  },
  sheet_range: {
    rowNoun: "row",
    params: [
      { kind: "entity", key: "document_id", entity: "document", required: true },
      { kind: "text", key: "sheet" },
      { kind: "text", key: "range", required: true, placeholder: "A1:B10" },
    ],
  },
  app: {
    rowNoun: "row",
    // An app's parameters are the app's — declared in its own manifest and
    // checked at fetch time. The two slots here are the ones a *definition*
    // fills: which installed app, and which of its sources.
    params: [
      { kind: "text", key: "app_uid", required: true },
      { kind: "text", key: "endpoint_id", required: true },
    ],
  },
};

export const sourceDescriptor = (source: WidgetSource | string): SourceDescriptor | undefined =>
  SOURCES[source as WidgetSource];

/**
 * Slots a widget still needs filled before it can draw anything.
 *
 * Derived from `required` rather than hand-written per source, so a new
 * parameter cannot be added in one place and forgotten in the other.
 */
export const unboundSlots = (binding: WidgetBinding): string[] => {
  const descriptor = sourceDescriptor(binding.source);
  if (!descriptor) return [];
  return descriptor.params
    .filter((param) => param.required && !binding[param.key])
    .map((param) => param.key as string);
};

/** The entity parameters a source can point at, in declaration order. */
export const entityParams = (source: WidgetSource | string): EntityParam[] =>
  (sourceDescriptor(source)?.params ?? []).filter(
    (param): param is EntityParam => param.kind === "entity"
  );

/** Whether this source takes filter conditions at all. */
export const acceptsFilters = (source: WidgetSource | string): boolean =>
  (sourceDescriptor(source)?.params ?? []).some((param) => param.kind === "filters");

/** The bucket a `task_counts` binding effectively groups by. */
export const effectiveBucket = (binding: WidgetBinding): string | undefined => {
  const param = (sourceDescriptor(binding.source)?.params ?? []).find(
    (candidate): candidate is EnumParam => candidate.kind === "enum" && candidate.key === "bucket"
  );
  if (!param) return undefined;
  const value = binding.bucket;
  return typeof value === "string" && param.values.includes(value) ? value : param.fallback;
};
