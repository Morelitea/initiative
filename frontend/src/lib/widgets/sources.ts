/**
 * What each binding source *is* — the one description of a data view.
 *
 * Three, and they are not variations on a theme. A **query** is a statement
 * over this guild's datasets. A **sheet_range** is a cell range in a
 * spreadsheet document; it answers with the same columns and rows a statement
 * does, and becomes a statement itself once documents are queryable. An **app**
 * is an installed listing's own endpoint, whose parameters are declared in its
 * manifest and checked at fetch time — the two slots here are the ones a
 * *definition* fills: which app, and which of its sources.
 *
 * The backend deliberately does not declare binding parameters: they belong to
 * the fetcher that consumes them, and mirroring them server-side would mean
 * maintaining every parameter twice. So this is a *description*, not a second
 * validator, and it is what lets three surfaces stop restating the same
 * knowledge:
 *
 * - `unboundSlots()` — which parameters a binding still needs (from `required`)
 * - the config dialog's controls
 * - the provenance line on every tile
 */

import type { WidgetBinding } from "@/hooks/useWidgetData";
import type { WidgetSource } from "@/lib/widgets/dataShapes";

/** An entity a binding can point at. The kind decides which of the canvas's
 *  already-cached list queries resolves it to a name — never a fetch of its
 *  own, so a dense canvas costs no extra requests. */
export type EntityKind = "document";

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
}

/** Free text the source parses — a sheet name, an A1 range. */
export interface TextParam extends BaseParam {
  kind: "text";
  placeholder?: string;
}

/** A statement. Its own kind rather than free text: it is many lines, it is
 *  checked by the server before it runs, and the builder that writes it needs
 *  somewhere to say so. */
export interface SqlParam extends BaseParam {
  kind: "sql";
}

export type SourceParam = EntityParam | TextParam | SqlParam;

export interface SourceDescriptor {
  /** Singular noun for one row, for counts and empty states. Rendered through
   *  i18n plurals, never concatenated. */
  rowNoun: "row";
  params: readonly SourceParam[];
}

export const SOURCES: Record<WidgetSource, SourceDescriptor> = {
  query: {
    rowNoun: "row",
    // One parameter, and it is the whole binding: a statement says what it
    // reads, what it narrows to and what it returns, so there is no project to
    // pick and no filter to build beside it.
    params: [{ kind: "sql", key: "sql", required: true }],
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

/** The parameters to offer for one source. Every widget bound to a statement
 *  is configured the same way, so there is nothing here that varies by widget
 *  — what varies is the *shape* it draws, which the mapping settles. */
export const paramsFor = (source: WidgetSource | string): readonly SourceParam[] =>
  sourceDescriptor(source)?.params ?? [];
