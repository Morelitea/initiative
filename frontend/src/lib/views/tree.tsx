import { Fragment, memo, type ReactNode } from "react";

import { nonEmptyPropertySummaries } from "@/components/properties/propertyHelpers";
import { cn } from "@/lib/utils";

import {
  FIELD_RENDERERS,
  type FieldDef,
  isEmptyValue,
  type ViewEnv,
  type ViewItem,
  type ViewVariant,
} from "./fields";
import { type PluginOnItems, PluginPartView } from "./plugins";

/** A view as data: a registered part, its props, and what it holds. The same
 *  shape the plug-in SDK uses for parts. */
export type ViewNode = {
  type: string;
  props?: Record<string, unknown>;
  children?: ViewNode[];
};

/** What every item in one view shares. Made once per view, not per item, so
 *  the memoized items skip re-rendering until it changes. */
export type ViewContext = {
  /** In order: built-ins, properties in definition order, then plug-ins'. */
  fields: ReadonlyMap<string, FieldDef>;
  /** The plug-ins whose parts a tree may place, by install. */
  plugins?: ReadonlyMap<number, PluginOnItems>;
  /** A board's card. */
  card?: ViewNode;
  variant: ViewVariant;
  isHidden: (fieldId: string) => boolean;
  env: ViewEnv;
};

/**
 * A part turns its node into elements, drawing its children with the parts it
 * was drawn with. Parts call no hooks — they run inside the tree's render — so
 * anything that needs one is a component a part returns, as the field
 * renderers are.
 */
type Part<I> = (node: ViewNode, item: I, view: ViewContext, parts: Parts<I>) => ReactNode;

/** The parts a tree of one kind of item can hold, by node type. */
export type Parts<I> = Readonly<Record<string, Part<I>>>;

/** Draws one item through a tree. Unknown parts and fields draw nothing. */
export const renderNode = <I,>(
  node: ViewNode,
  item: I,
  view: ViewContext,
  parts: Parts<I>
): ReactNode =>
  Object.hasOwn(parts, node.type) ? parts[node.type](node, item, view, parts) : null;

const renderChildren = <I,>(
  node: ViewNode,
  item: I,
  view: ViewContext,
  parts: Parts<I>
): ReactNode =>
  node.children?.map((child, index) => (
    // biome-ignore lint/suspicious/noArrayIndexKey: a tree is fixed for the life of a view
    <Fragment key={index}>{renderNode(child, item, view, parts)}</Fragment>
  ));

const renderField = (
  field: FieldDef,
  value: unknown,
  item: ViewItem,
  view: ViewContext,
  key?: number
): ReactNode => {
  if ((field.hideable && view.isHidden(field.id)) || isEmptyValue(value)) return null;
  const Renderer = FIELD_RENDERERS[field.kind];
  return (
    <Renderer
      key={key}
      value={value}
      item={item}
      field={field}
      variant={view.variant}
      env={view.env}
    />
  );
};

/** A property whose definition has not arrived: drawn, and never hidden. */
const UNLOADED_PROPERTY: FieldDef = {
  id: "",
  kind: "property",
  source: "property",
  label: "",
  hideable: false,
  value: () => null,
};

// A view's property fields by definition id, indexed once per view rather than
// searched once per card.
const propertyIndexes = new WeakMap<ReadonlyMap<string, FieldDef>, Map<number, FieldDef>>();

const propertyField = (
  fields: ReadonlyMap<string, FieldDef>,
  propertyId: number
): FieldDef | undefined => {
  let index = propertyIndexes.get(fields);
  if (!index) {
    index = new Map();
    for (const field of fields.values()) {
      if (field.propertyId !== undefined) index.set(field.propertyId, field);
    }
    propertyIndexes.set(fields, index);
  }
  return index.get(propertyId);
};

const PROPERTY_BY_ID = /^property:([1-9][0-9]*)$/;

/** The field a node names. A stored view names a property by its definition
 *  id, which the server checks; the fields are keyed as the table's columns
 *  are, by name, and a property may be named with digits. */
const fieldNamed = (
  fields: ReadonlyMap<string, FieldDef>,
  node: ViewNode
): FieldDef | undefined => {
  const id = String(node.props?.field);
  const byId = PROPERTY_BY_ID.exec(id);
  return byId ? propertyField(fields, Number(byId[1])) : fields.get(id);
};

type StackProps = {
  direction?: "column" | "row";
  gap?: "xs" | "sm";
  wrap?: boolean;
  /** In a column, items keep their own width rather than filling it; in a
   *  row, they keep their own height. */
  align?: "start";
  tone?: "muted";
};

const GAP = { xs: "gap-1", sm: "gap-2" };
const SPACE = { xs: "space-y-1", sm: "space-y-2" };
const TONE = { muted: "wrap-break-word text-muted-foreground text-xs" };

const stackClassName = ({ direction, gap = "xs", wrap, align, tone }: StackProps): string => {
  if (direction === "row") {
    return cn("flex min-w-0", wrap && "flex-wrap", align === "start" && "items-start", GAP[gap]);
  }
  // A column whose items fill it is a plain block, spaced line by line.
  return align === "start"
    ? cn("flex w-full min-w-0 flex-col items-start text-left", GAP[gap], tone && TONE[tone])
    : cn("w-full min-w-0", SPACE[gap], tone && TONE[tone]);
};

// A region of an item's page: it draws its parts in a column, and places
// itself on the page's grid. The side column sits above the main one until
// there is room beside it.
const region =
  (className: string) =>
  <I,>(node: ViewNode, item: I, view: ViewContext, parts: Parts<I>) => (
    <div className={cn("min-w-0", className)}>{renderChildren(node, item, view, parts)}</div>
  );

/** Arrangement, for a tree of any kind of item. */
export const LAYOUT_PARTS = {
  stack: <I,>(node: ViewNode, item: I, view: ViewContext, parts: Parts<I>) => (
    <div className={stackClassName((node.props ?? {}) as StackProps)}>
      {renderChildren(node, item, view, parts)}
    </div>
  ),
  /** An item's own page, which holds its header, main and side regions. */
  page: <I,>(node: ViewNode, item: I, view: ViewContext, parts: Parts<I>) => (
    <div className="grid canvas-md:grid-cols-[minmax(0,1fr)_20rem] gap-6">
      {renderChildren(node, item, view, parts)}
    </div>
  ),
  header: region("space-y-2 canvas-md:col-span-2"),
  main: region(
    "order-2 space-y-6 canvas-md:order-none canvas-md:col-start-1 canvas-md:row-start-2"
  ),
  side: region(
    "order-1 space-y-4 canvas-md:order-none canvas-md:col-start-2 canvas-md:row-start-2"
  ),
  /** A bordered group of parts. */
  section: <I,>(node: ViewNode, item: I, view: ViewContext, parts: Parts<I>) => (
    <section className="space-y-4 rounded-lg border bg-card p-4 text-card-foreground shadow-sm">
      {renderChildren(node, item, view, parts)}
    </section>
  ),
};

const PARTS: Parts<ViewItem> = {
  ...LAYOUT_PARTS,
  // The board draws the card's frame, which carries the drag and the measuring;
  // the card lays out what is inside it.
  card: (node, item, view, parts) => renderChildren(node, item, view, parts),
  field: (node, item, view) => {
    const field = fieldNamed(view.fields, node);
    return field ? renderField(field, field.value(item), item, view) : null;
  },
  // Every property the item carries, in its own order: a shipped tree cannot
  // name them. Each is hidden by its own field, found by definition id.
  properties: (_node, item, view) =>
    nonEmptyPropertySummaries(item.properties).map((summary) =>
      renderField(
        propertyField(view.fields, summary.property_id) ?? UNLOADED_PROPERTY,
        summary,
        item,
        view,
        summary.property_id
      )
    ),
  plugin: (node, item, view) => (
    <PluginPartView
      plugins={view.plugins}
      pluginId={Number(node.props?.plugin)}
      partId={String(node.props?.part)}
      task={item}
    />
  ),
};

/** The fields a tree draws: those it names, and every property where it
 *  draws them all. What the Fields menu offers to hide. */
export const drawnFields = (node: ViewNode, fields: ReadonlyMap<string, FieldDef>): FieldDef[] => {
  const named = new Set<string>();
  let properties = false;
  const walk = (part: ViewNode) => {
    if (part.type === "field") {
      const field = fieldNamed(fields, part);
      if (field) named.add(field.id);
    }
    if (part.type === "properties") properties = true;
    part.children?.forEach(walk);
  };
  walk(node);
  return [...fields.values()].filter(
    (field) => named.has(field.id) || (properties && field.source === "property")
  );
};

/** Draws one item of a collection through a tree. */
export const ViewTree = memo(function ViewTree({
  node,
  item,
  view,
}: {
  node: ViewNode;
  item: ViewItem;
  view: ViewContext;
}) {
  return renderNode(node, item, view, PARTS);
});
