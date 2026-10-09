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
 * A part turns its node into elements. Parts call no hooks — they run inside
 * `ViewTree`'s render — so anything that needs one is a component a part
 * returns, as the field renderers are.
 */
type Part = (node: ViewNode, item: ViewItem, view: ViewContext) => ReactNode;

const renderNode = (node: ViewNode, item: ViewItem, view: ViewContext): ReactNode =>
  Object.hasOwn(PARTS, node.type) ? PARTS[node.type](node, item, view) : null;

const renderChildren = (node: ViewNode, item: ViewItem, view: ViewContext): ReactNode =>
  node.children?.map((child, index) => (
    // biome-ignore lint/suspicious/noArrayIndexKey: a tree is fixed for the life of a view
    <Fragment key={index}>{renderNode(child, item, view)}</Fragment>
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
  /** Items keep their own width rather than filling the column. */
  align?: "start";
  tone?: "muted";
};

const GAP = { xs: "gap-1", sm: "gap-2" };
const SPACE = { xs: "space-y-1", sm: "space-y-2" };
const TONE = { muted: "wrap-break-word text-muted-foreground text-xs" };

const stackClassName = ({ direction, gap = "xs", wrap, align, tone }: StackProps): string => {
  if (direction === "row") return cn("flex min-w-0", wrap && "flex-wrap", GAP[gap]);
  // A column whose items fill it is a plain block, spaced line by line.
  return align === "start"
    ? cn("flex w-full min-w-0 flex-col items-start text-left", GAP[gap], tone && TONE[tone])
    : cn("w-full min-w-0", SPACE[gap], tone && TONE[tone]);
};

const PARTS: Record<string, Part> = {
  // The board draws the card's frame, which carries the drag and the measuring;
  // the card lays out what is inside it.
  card: (node, item, view) => renderChildren(node, item, view),
  stack: (node, item, view) => (
    <div className={stackClassName((node.props ?? {}) as StackProps)}>
      {renderChildren(node, item, view)}
    </div>
  ),
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

/** Draws one item through a tree. Unknown parts and fields draw nothing. */
export const ViewTree = memo(function ViewTree({
  node,
  item,
  view,
}: {
  node: ViewNode;
  item: ViewItem;
  view: ViewContext;
}) {
  return renderNode(node, item, view);
});
