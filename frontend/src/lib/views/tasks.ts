import { Ban, MessageSquare } from "lucide-react";

import type {
  ItemLayoutDefinitionInput,
  PropertyDefinitionRead,
} from "@/api/generated/initiativeAPI.schemas";
import { namePropertyColumns } from "@/components/properties/propertyColumns";
import { isEmptyPropertyValue } from "@/components/properties/propertyHelpers";
import { iconForPropertyType } from "@/components/properties/propertyTypeIcons";

import { type FieldDef, propertyFieldId } from "./fields";
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
 * the initiative defines, then the plug-ins' (`pluginFields`). Each is keyed
 * by the id a view stores it under, which a table's column shares; two
 * properties that share a name are told apart in their labels.
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
      ({ definition, label }): FieldDef => ({
        id: propertyFieldId(definition.id),
        kind: "property",
        source: "property",
        label,
        hideable: true,
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

/** The table's columns as shipped, in order: the fields it draws as columns. */
export const TASK_COLUMNS = ["title", "startDate", "dueDate", "priority", "tags", "comments"];

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

/** An item page's regions, in the order a page holds them. */
export const PAGE_REGIONS = ["header", "main", "side"] as const;

export type Region = (typeof PAGE_REGIONS)[number];

/** An item layout's regions, as stored: one it leaves out is drawn as shipped. */
export type StoredRegions = Partial<Record<Region, ViewNode[] | null>>;

/**
 * A task's page as shipped: the title, who made it and what else can be done
 * with it across the top; what the task is in the main column; and the fields
 * that place it beside them. On one column, the fields follow the description.
 */
export const TASK_PAGE_REGIONS: Record<Region, ViewNode[]> = {
  header: [
    {
      type: "stack",
      props: { direction: "row", gap: "sm", align: "start" },
      children: [field("title"), { type: "actions" }],
    },
    { type: "byline" },
    { type: "notice" },
  ],
  main: [
    at(1, { type: "section", children: [field("description")] }),
    at(3, field("checklist")),
    at(4, { type: "case" }),
    at(6, { type: "comments" }),
  ],
  side: [
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
};

/** The page parts that edit a field. */
const EDITS_A_FIELD = new Set(["field", "status", "dates", "properties"]);

const placedAs = (node: ViewNode) =>
  node.type === "field" ? `field:${String(node.props?.field)}` : node.type;

const nodesIn = (nodes: ViewNode[]): ViewNode[] =>
  nodes.flatMap((node) => [node, ...nodesIn(node.children ?? [])]);

/** What the shipped page edits, in its order. */
const SHIPPED_FIELDS = nodesIn(Object.values(TASK_PAGE_REGIONS).flat()).filter((node) =>
  EDITS_A_FIELD.has(node.type)
);

/** Each region as stored, or as shipped where the layout leaves it out. */
const regionsOf = (stored: StoredRegions | null | undefined): Record<Region, ViewNode[]> => ({
  header: stored?.header ?? TASK_PAGE_REGIONS.header,
  main: stored?.main ?? TASK_PAGE_REGIONS.main,
  side: stored?.side ?? TASK_PAGE_REGIONS.side,
});

/** What the shipped page edits and the regions place nowhere, in its order. */
export const unplacedFields = (regions: Record<Region, ViewNode[]>): ViewNode[] => {
  const placed = new Set(nodesIn(Object.values(regions).flat()).map(placedAs));
  return SHIPPED_FIELDS.filter((node) => !placed.has(placedAs(node)));
};

/** A page part that edits a field: placed nowhere, it is drawn under More
 *  fields rather than gone. */
export const editsAField = (node: ViewNode): boolean => EDITS_A_FIELD.has(node.type);

/** A task's page as one tree to edit by path: the page, holding its header,
 *  main and side in that order. */
export const taskPageRoot = (stored: StoredRegions | null | undefined): ViewNode => {
  const regions = regionsOf(stored);
  return {
    type: "page",
    children: PAGE_REGIONS.map((region) => ({ type: region, children: regions[region] })),
  };
};

/** The layout a page tree is stored as. Every region is stored, and without
 *  the shipped page's one-column `order`: a stored region keeps its own. */
export const storedLayout = (root: ViewNode): ItemLayoutDefinitionInput => {
  const region = (index: number) =>
    (root.children?.[index]?.children ?? []).map(({ props, ...node }) => {
      const { order: _order, ...rest } = props ?? {};
      return Object.keys(rest).length > 0 ? { ...node, props: rest } : node;
    });
  return {
    header: region(0),
    main: region(1),
    side: region(2),
  } as ItemLayoutDefinitionInput;
};

/**
 * A task's page from its project's item layout: each region as stored, or as
 * shipped where the layout leaves it out. What the shipped page edits and the
 * layout places nowhere is drawn in a "More fields" section at the side, so a
 * field still has a place on a page nobody laid out for it. A stored part
 * carries no `order`, so on one column a stored region keeps its own order.
 */
export const taskPageTree = (
  stored: StoredRegions | null | undefined,
  moreFields: string
): ViewNode => {
  const regions = regionsOf(stored);
  const unplaced = unplacedFields(regions);
  // Last on one column, after whatever the regions hold.
  const side = unplaced.length
    ? [
        ...regions.side,
        at(7, { type: "section", props: { title: moreFields }, children: unplaced }),
      ]
    : regions.side;
  return {
    type: "page",
    children: [
      { type: "header", children: regions.header },
      { type: "main", children: regions.main },
      { type: "side", children: side },
    ],
  };
};

/** The page as shipped. */
export const TASK_PAGE: ViewNode = taskPageTree(undefined, "");
