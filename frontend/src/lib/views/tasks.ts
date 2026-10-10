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
 * the initiative defines, then the plug-ins' (`pluginFields`). A property's id
 * is its table column's id, so the Fields menu and the table name it
 * identically and two that share a name stay apart.
 */
export const taskFields = (
  definitions: PropertyDefinitionRead[],
  plugins: FieldDef[] = []
): Map<string, FieldDef> => {
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
    ...plugins,
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

/** A part of a page's column, and where it falls once the page is one column. */
const at = (order: number, node: ViewNode): ViewNode => ({
  ...node,
  props: { ...node.props, order },
});

/**
 * A task's page as shipped: the title, who made it and what else can be done
 * with it across the top; what the task is in the main column; and the fields
 * that place it beside them. On one column, the fields follow the description.
 */
export const TASK_PAGE: ViewNode = {
  type: "page",
  children: [
    {
      type: "header",
      children: [
        {
          type: "stack",
          props: { direction: "row", gap: "sm", align: "start" },
          children: [field("title"), { type: "actions" }],
        },
        { type: "byline" },
        { type: "notice" },
      ],
    },
    {
      type: "main",
      children: [
        at(1, { type: "section", children: [field("description")] }),
        at(3, field("checklist")),
        at(4, { type: "case" }),
        at(6, { type: "comments" }),
      ],
    },
    {
      type: "side",
      children: [
        at(2, {
          type: "section",
          children: [
            { type: "status" },
            field("priority"),
            field("assignees"),
            { type: "dates" },
            field("recurrence"),
            field("tags"),
            { type: "properties" },
          ],
        }),
        at(5, { type: "relations" }),
      ],
    },
  ],
};
