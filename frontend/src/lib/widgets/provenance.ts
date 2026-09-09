/**
 * What a tile may say about where its data came from.
 *
 * Bounded on purpose. A reader is told the *kind* of thing a widget is showing
 * and, where a binding points at something they can resolve, its name. They are
 * never told the name or id of something they cannot see — a chip for an
 * unresolvable target says only that there is one.
 *
 * A statement says which datasets it read, which the server answers with; there
 * is no id to resolve and nothing further to disclose, because a query returns
 * what its reader already reaches.
 */

import type { WidgetBinding } from "@/hooks/useWidgetData";
import { type EntityKind, entityParams } from "@/lib/widgets/sources";

/** Names the canvas has already loaded, by kind. Never a fetch of its own: a
 *  dense canvas costs no extra requests. */
export interface EntityLabels {
  document: Map<number, string>;
  /** False while any lookup is still in flight. Nothing may be called
   *  unresolvable until this is true. */
  ready: boolean;
}

export const EMPTY_LABELS: EntityLabels = {
  document: new Map(),
  ready: false,
};

/** One resolved fact about a binding, as the line and popover draw it. */
export interface ProvenanceChip {
  key: string;
  /** The resolved name, or undefined when the viewer cannot resolve it. */
  label?: string;
  /** True once we know the id will not resolve for this viewer. */
  restricted: boolean;
}

const LABEL_MAPS: Record<EntityKind, keyof EntityLabels> = {
  document: "document",
};

const lookup = (labels: EntityLabels, kind: EntityKind, id: number): string | undefined =>
  (labels[LABEL_MAPS[kind]] as Map<number, string>).get(id);

/**
 * The entities a binding points at, resolved.
 *
 * A parameter with no value is simply absent from the result — a default is not
 * a fact worth a chip.
 */
export const bindingScope = (binding: WidgetBinding, labels: EntityLabels): ProvenanceChip[] =>
  entityParams(binding.source).flatMap((param) => {
    const id = binding[param.key];
    if (typeof id !== "number") return [];
    const label = lookup(labels, param.entity, id);
    return [{ key: param.key as string, label, restricted: !label && labels.ready }];
  });

/** The datasets a statement read, as chips. Answered by the server rather than
 *  parsed here: what a statement resolves to is the validator's answer, and a
 *  second reading of the same SQL could only disagree with it. */
export const queryScope = (relations: readonly string[]): ProvenanceChip[] =>
  relations.map((relation) => ({ key: relation, label: relation, restricted: false }));
