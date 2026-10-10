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
  /** In order: built-ins, then properties in definition order. */
  fields: ReadonlyMap<string, FieldDef>;
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
// itself on the page's grid.
const region =
  (className: string) =>
  <I,>(node: ViewNode, item: I, view: ViewContext, parts: Parts<I>) => (
    <div className={cn("min-w-0", className)}>{renderChildren(node, item, view, parts)}</div>
  );

// Where a part of a column falls once the page is a single column.
const ORDER: Record<number, string> = {
  1: "order-1 canvas-md:order-none",
  2: "order-2 canvas-md:order-none",
  3: "order-3 canvas-md:order-none",
  4: "order-4 canvas-md:order-none",
  5: "order-5 canvas-md:order-none",
  6: "order-6 canvas-md:order-none",
  7: "order-7 canvas-md:order-none",
  8: "order-8 canvas-md:order-none",
};

// A column of an item's page. Until there is room for the columns side by
// side, the page is one column and each column's parts join it, falling where
// their `order` prop puts them, so the two columns can interleave. A part
// that draws nothing takes no room.
const column =
  (className: string) =>
  <I,>(node: ViewNode, item: I, view: ViewContext, parts: Parts<I>) => (
    <div className={cn("canvas-md:flex contents canvas-md:min-w-0 canvas-md:flex-col", className)}>
      {node.children?.map((child, index) => (
        <div
          // biome-ignore lint/suspicious/noArrayIndexKey: a tree is fixed for the life of a view
          key={index}
          className={cn("min-w-0 empty:hidden", ORDER[Number(child.props?.order)])}
        >
          {renderNode(child, item, view, parts)}
        </div>
      ))}
    </div>
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
  main: column("canvas-md:col-start-1 canvas-md:row-start-2 canvas-md:gap-6"),
  side: column("canvas-md:col-start-2 canvas-md:row-start-2 canvas-md:gap-4"),
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
    const field = view.fields.get(String(node.props?.field));
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
