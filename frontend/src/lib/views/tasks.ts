import { Ban, MessageSquare } from "lucide-react";

import type { PropertyDefinitionRead } from "@/api/generated/initiativeAPI.schemas";
import { namePropertyColumns } from "@/components/properties/propertyColumns";
import { isEmptyPropertyValue } from "@/components/properties/propertyHelpers";
import { iconForPropertyType } from "@/components/properties/propertyTypeIcons";

import type { FieldDef } from "./fields";
import type { ViewNode } from "./tree";

const builtin = (
  field: Omit<FieldDef, "source" | "label" | "hideable"> & Partial<FieldDef>
): FieldDef => ({
  source: "builtin",
  label: `kanban.fields.${field.id}`,
  hideable: true,
  ...field,
});

/**
 * Everything a task view can show: the built-ins, then one field per property
 * the initiative defines. A property's id is its table column's id, so the
 * Fields menu and the table name it identically and two that share a name
 * stay apart.
 */
export const taskFields = (definitions: PropertyDefinitionRead[]): Map<string, FieldDef> => {
  const fields: FieldDef[] = [
    builtin({
      id: "title",
      kind: "title",
      // What a table's column has always been called.
      label: "table.taskColumn",
      hideable: false,
      value: (task) => task.title,
    }),
    builtin({ id: "description", kind: "excerpt", value: (task) => task.description_excerpt }),
    builtin({ id: "assignees", kind: "people", value: (task) => task.assignees }),
    builtin({
      id: "startDate",
      kind: "date",
      phrase: "kanban.starts",
      past: "primary",
      value: (task) => task.start_date,
    }),
    builtin({
      id: "dueDate",
      kind: "date",
      phrase: "kanban.due",
      past: "destructive",
      value: (task) => task.due_date,
    }),
    builtin({ id: "recurrence", kind: "recurrence", value: (task) => task.recurrence }),
    builtin({ id: "checklist", kind: "checklist", value: (task) => task.checklist_progress }),
    builtin({
      id: "priority",
      kind: "priority",
      phrase: "kanban.priority",
      value: (task) => task.priority,
    }),
    // A count of none shows nothing.
    builtin({
      id: "comments",
      kind: "count",
      icon: MessageSquare,
      value: (task) => task.comment_count || null,
    }),
    // The signal the retired Blocked column used to give, keeping itself
    // current: it goes when the last thing holding this up is finished.
    builtin({
      id: "blockers",
      kind: "count",
      icon: Ban,
      tone: "warning",
      phrase: "relations:blockers.label",
      value: (task) => task.blocked_by_open_count || null,
    }),
    builtin({ id: "tags", kind: "tags", value: (task) => task.tags }),
    ...namePropertyColumns(definitions).map(
      ({ definition, id, label }): FieldDef => ({
        id,
        kind: "property",
        source: "property",
        label,
        hideable: true,
        propertyId: definition.id,
        icon: iconForPropertyType(definition.type),
        value: (task) => {
          const summary = task.properties?.find((s) => s.property_id === definition.id);
          return summary && !isEmptyPropertyValue(summary.value) ? summary : null;
        },
      })
    ),
  ];
  return new Map(fields.map((field) => [field.id, field]));
};

const field = (id: string): ViewNode => ({ type: "field", props: { field: id } });

/** The board's card as shipped. */
export const TASK_CARD: ViewNode = {
  type: "card",
  children: [
    {
      type: "stack",
      props: { align: "start" },
      children: [
        field("title"),
        field("description"),
        {
          type: "stack",
          props: { tone: "muted" },
          children: [field("assignees"), field("startDate"), field("dueDate"), field("recurrence")],
        },
        field("checklist"),
      ],
    },
    {
      type: "stack",
      props: { direction: "row", gap: "sm", wrap: true },
      children: [
        field("priority"),
        field("comments"),
        field("blockers"),
        field("tags"),
        { type: "properties" },
      ],
    },
  ],
};
