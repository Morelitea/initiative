/**
 * Saying what a widget is showing — and only what this viewer may be told.
 *
 * A tile has never described its own data view, which is the first thing anyone
 * asks of a dashboard: where do these numbers come from, and what is filtered
 * out? The answer is assembled here and drawn by `WidgetProvenance`.
 *
 * One rule shapes the whole module:
 *
 * > **Render from what the viewer can resolve, never from what the binding
 * > says.**
 *
 * A binding holds ids. A name is not in the definition — it is the result of a
 * fetch, made under the viewer's own session and decided by the same gates that
 * decide the widget's rows. So an id is looked up in {@link EntityLabels},
 * which is built from the canvas's own already-cached list queries, and an id
 * that is not in there renders as *absent* — never the stored name, never the
 * id, never a type-specific detail. The viewer already knows a widget of that
 * source kind sits on the canvas; they learn nothing further.
 *
 * {@link EntityLabels.ready} is why the lookups carry a loading flag at all: an
 * id that has not resolved *yet* must not render as unresolvable, or every tile
 * would flash a false claim on its way to the truth.
 *
 * Everything here is pure. `t` arrives as a parameter, per the app's convention
 * for translated helpers outside React.
 */

import type { TFunction } from "i18next";

import type { WidgetBinding } from "@/hooks/useWidgetData";
import {
  type ConditionValue,
  type FilterLeaf,
  type FilterNode,
  fieldSpec,
  isGroup,
  isRelativeDate,
} from "@/lib/widgets/conditions";
import { type EntityKind, entityParams } from "@/lib/widgets/sources";

/** The namespaces these helpers read. Named so a caller passes the `t` from a
 *  `useTranslation` over the same set and the keys below stay checked. */
export type ProvenanceT = TFunction<["dashboards", "tasks", "common"]>;

/**
 * Names for the ids a binding may mention, as far as *this viewer* can see
 * them.
 *
 * Every map is the viewer's own RLS-gated list; membership in it is the whole
 * authorization decision. Absence is not distinguished from non-existence, on
 * purpose.
 */
export interface EntityLabels {
  project: Map<number, string>;
  calendar: Map<number, string>;
  counterGroup: Map<number, string>;
  counter: Map<number, string>;
  document: Map<number, string>;
  member: Map<number, string>;
  tag: Map<number, string>;
  /** False while any lookup is still in flight. Nothing may be called
   *  unresolvable until this is true. */
  ready: boolean;
}

export const EMPTY_LABELS: EntityLabels = {
  project: new Map(),
  calendar: new Map(),
  counterGroup: new Map(),
  counter: new Map(),
  document: new Map(),
  member: new Map(),
  tag: new Map(),
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
  project: "project",
  calendar: "calendar",
  counter_group: "counterGroup",
  counter: "counter",
  document: "document",
};

const lookup = (labels: EntityLabels, kind: EntityKind, id: number): string | undefined =>
  (labels[LABEL_MAPS[kind]] as Map<number, string>).get(id);

/**
 * The entities a binding points at, resolved.
 *
 * A parameter with no value is simply absent from the result — "all projects"
 * is the default, not a fact worth a chip.
 */
export const bindingScope = (binding: WidgetBinding, labels: EntityLabels): ProvenanceChip[] =>
  entityParams(binding.source).flatMap((param) => {
    const id = binding[param.key];
    if (typeof id !== "number") return [];
    const label = lookup(labels, param.entity, id);
    return [{ key: param.key as string, label, restricted: !label && labels.ready }];
  });

// --- filters as sentences ---------------------------------------------------

const listValues = (raw: ConditionValue | undefined): (string | number)[] => {
  if (Array.isArray(raw)) return raw;
  if (raw === null || raw === undefined || isRelativeDate(raw)) return [];
  return [raw as string | number];
};

/**
 * One filter value as text.
 *
 * Ids go through the viewer's own lookups; anything that does not resolve is
 * counted rather than named, so a line reads "Ada, and 2 you can't see" instead
 * of leaking two names or silently dropping them.
 */
const describeValues = (leaf: FilterLeaf, labels: EntityLabels, t: ProvenanceT): string => {
  const spec = fieldSpec(leaf.field);
  const values = listValues(leaf.value);
  if (!values.length) return "";

  const named: string[] = [];
  let hidden = 0;

  for (const value of values) {
    switch (spec?.kind) {
      case "status_category":
        named.push(t(`tasks:statusCategory.${value}`, { defaultValue: String(value) }));
        break;
      case "priority":
        named.push(t(`tasks:priority.${value}`, { defaultValue: String(value) }));
        break;
      case "member": {
        // "me" is the DSL's own token for the requesting user, and it is the
        // one id-shaped value that needs no lookup.
        if (value === "me") {
          named.push(t("dashboards:provenance.me"));
          break;
        }
        const name = labels.member.get(Number(value));
        if (name) named.push(name);
        else if (labels.ready) hidden += 1;
        break;
      }
      case "tag": {
        const name = labels.tag.get(Number(value));
        if (name) named.push(name);
        else if (labels.ready) hidden += 1;
        break;
      }
      case "project": {
        const name = labels.project.get(Number(value));
        if (name) named.push(name);
        else if (labels.ready) hidden += 1;
        break;
      }
      case "boolean":
        named.push(value ? t("common:yes") : t("common:no"));
        break;
      default:
        named.push(String(value));
    }
  }

  if (hidden > 0) {
    const restricted = t("dashboards:provenance.hiddenValues", { count: hidden });
    return named.length
      ? t("dashboards:provenance.joinHidden", { named: named.join(", "), restricted })
      : restricted;
  }
  return named.join(", ");
};

const describeDate = (
  value: ConditionValue | undefined,
  t: ProvenanceT,
  formatDate: (epoch: number) => string
): string => {
  if (isRelativeDate(value)) {
    const days = value.relative;
    if (days === 0) return t("dashboards:provenance.today");
    return days > 0
      ? t("dashboards:provenance.inDays", { count: days })
      : t("dashboards:provenance.agoDays", { count: Math.abs(days) });
  }
  if (typeof value === "string") {
    const parsed = Date.parse(value);
    if (!Number.isNaN(parsed)) return formatDate(parsed);
  }
  return String(value ?? "");
};

/** One comparison as a sentence. Field name and operator are app-owned strings;
 *  values go through the viewer's own lookups. */
export const describeLeaf = (
  leaf: FilterLeaf,
  labels: EntityLabels,
  t: ProvenanceT,
  formatDate: (epoch: number) => string
): string => {
  const field = t(`dashboards:filterField.${leaf.field}`, { defaultValue: leaf.field });
  // `not_` rather than a `.not` suffix: the phrases are a flat map, and a key
  // cannot be both a string and a parent.
  const prefix = leaf.negate ? "not_" : "";

  if (leaf.op === "is_null") {
    return t(`dashboards:filterPhrase.${prefix}is_null`, { field, defaultValue: field });
  }
  const spec = fieldSpec(leaf.field);
  const value =
    spec?.kind === "date"
      ? describeDate(leaf.value, t, formatDate)
      : describeValues(leaf, labels, t);

  return t(`dashboards:filterPhrase.${prefix}${leaf.op}`, {
    field,
    value,
    defaultValue: `${field} ${value}`,
  });
};

/** Every comparison in a filter, flattened. A group contributes its children
 *  joined by its own logic word, so an OR reads as one line rather than
 *  dissolving into unrelated ANDs. */
export const describeConditions = (
  nodes: FilterNode[],
  labels: EntityLabels,
  t: ProvenanceT,
  formatDate: (epoch: number) => string
): string[] =>
  nodes.map((node) => {
    if (!isGroup(node)) return describeLeaf(node, labels, t, formatDate);
    const joiner = t(`dashboards:provenance.${node.logic}`);
    return node.conditions
      .map((child) =>
        isGroup(child)
          ? describeConditions([child], labels, t, formatDate).join("")
          : describeLeaf(child, labels, t, formatDate)
      )
      .join(` ${joiner} `);
  });
