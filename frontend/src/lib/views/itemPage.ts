/**
 * An item's own page laid out from a tree, for any kind of item that has one
 * (a task, an event): its regions, where each part falls once the page is one
 * column, the fields placed nowhere, and the layout a page is stored as.
 */

import type { ItemLayoutDefinitionInput } from "@/api/generated/initiativeAPI.schemas";

import type { ViewNode } from "./tree";

/** An item page's regions, in the order a page holds them. */
export const PAGE_REGIONS = ["header", "main", "side"] as const;

export type Region = (typeof PAGE_REGIONS)[number];

/** An item layout's regions, as stored: one it leaves out is drawn as shipped. */
export type StoredRegions = Partial<Record<Region, ViewNode[] | null>>;

/** A part of a page's column, and where it falls once the page is one column. */
export const at = (order: number, node: ViewNode): ViewNode => ({
  ...node,
  props: { ...node.props, order },
});

const placedAs = (node: ViewNode) =>
  node.type === "field" ? `field:${String(node.props?.field)}` : node.type;

const nodesIn = (nodes: ViewNode[]): ViewNode[] =>
  nodes.flatMap((node) => [node, ...nodesIn(node.children ?? [])]);

/** What a column's part is known by: its kind or field, or a group's first. */
const anchorOf = (node: ViewNode): string | undefined =>
  node.type === "section" || node.type === "stack"
    ? (node.children ?? []).map(anchorOf).find((anchor) => anchor !== undefined)
    : placedAs(node);

/** A part without the shipped page's one-column `order`, at any depth: a
 *  shipped part may have been moved into a section. */
const withoutOrder = ({ props, children, ...node }: ViewNode): ViewNode => {
  const { order: _order, ...rest } = props ?? {};
  return {
    ...node,
    ...(Object.keys(rest).length > 0 ? { props: rest } : {}),
    ...(children ? { children: children.map(withoutOrder) } : {}),
  };
};

/** The layout a page tree is stored as. Every region is stored, and without
 *  the shipped page's one-column `order`: a stored region keeps its own. */
export const storedLayout = (root: ViewNode): ItemLayoutDefinitionInput => {
  const region = (index: number) => (root.children?.[index]?.children ?? []).map(withoutOrder);
  return {
    header: region(0),
    main: region(1),
    side: region(2),
  } as ItemLayoutDefinitionInput;
};

/** One kind of item's page: as shipped, and as a stored layout draws it. */
export interface ItemPageKind {
  /** The regions as shipped. */
  shipped: Record<Region, ViewNode[]>;
  /** Whether a part edits a field: placed nowhere, it is drawn under More
   *  fields rather than gone. */
  editsAField: (node: ViewNode) => boolean;
  /** What the shipped page edits and `regions` place nowhere, in its order. */
  unplacedFields: (regions: Record<Region, ViewNode[]>) => ViewNode[];
  /** The page as one tree to edit by path: the page, holding its header,
   *  main and side in that order. */
  root: (stored: StoredRegions | null | undefined) => ViewNode;
  /**
   * The page from a stored layout: each region as stored, or as shipped where
   * the layout leaves it out. What the shipped page edits and the layout
   * places nowhere is drawn in a "More fields" section at the side, so a
   * field still has a place on a page nobody laid out for it. A stored part
   * carries no `order`: where it falls on one column is worked out here, so a
   * page laid out anew still reads as the shipped one does on a phone.
   */
  tree: (stored: StoredRegions | null | undefined, moreFields: string) => ViewNode;
}

/**
 * A kind of item's page, from how it ships: its regions, with each column
 * part's one-column `order`; the part types that edit a field; and where More
 * fields falls on one column, after everything else.
 */
export const itemPageKind = ({
  shipped,
  fieldParts,
  moreOrder,
}: {
  shipped: Record<Region, ViewNode[]>;
  fieldParts: readonly string[];
  moreOrder: number;
}): ItemPageKind => {
  const editing = new Set(fieldParts);
  const editsAField = (node: ViewNode) => editing.has(node.type);
  /** What the shipped page edits, in its order. */
  const shippedFields = nodesIn(Object.values(shipped).flat()).filter(editsAField);
  /** Where the shipped page puts each of its column parts on one column. */
  const shippedOrder = new Map(
    [...shipped.main, ...shipped.side].map((node) => [anchorOf(node), Number(node.props?.order)])
  );

  /**
   * A column's parts with where each falls once the page is one column, as
   * the shipped page interleaves its columns: a part the shipped page has
   * falls where it puts it, any other right after the part before it, and a
   * column keeps its own order (a part never falls before one above it).
   * Parts that fall together keep the main column's ahead of the side's.
   */
  const ordered = (parts: ViewNode[], column: "main" | "side"): ViewNode[] => {
    const known = parts.map((part) => shippedOrder.get(anchorOf(part)));
    let order =
      known.find((each) => each !== undefined) ?? Number(shipped[column][0]?.props?.order ?? 1);
    return parts.map((part, index) => {
      order = Math.max(order, known[index] ?? order);
      return at(order, part);
    });
  };

  const regionsOf = (stored: StoredRegions | null | undefined): Record<Region, ViewNode[]> => ({
    header: stored?.header ?? shipped.header,
    main: stored?.main ?? shipped.main,
    side: stored?.side ?? shipped.side,
  });

  const unplacedFields = (regions: Record<Region, ViewNode[]>) => {
    const placed = new Set(nodesIn(Object.values(regions).flat()).map(placedAs));
    return shippedFields.filter((node) => !placed.has(placedAs(node)));
  };

  return {
    shipped,
    editsAField,
    unplacedFields,
    root: (stored) => {
      const regions = regionsOf(stored);
      return {
        type: "page",
        children: PAGE_REGIONS.map((region) => ({ type: region, children: regions[region] })),
      };
    },
    tree: (stored, moreFields) => {
      const regions = regionsOf(stored);
      const unplaced = unplacedFields(regions);
      const side = ordered(regions.side, "side");
      return {
        type: "page",
        children: [
          { type: "header", children: regions.header },
          { type: "main", children: ordered(regions.main, "main") },
          {
            type: "side",
            children: unplaced.length
              ? [
                  ...side,
                  // Last on one column, after whatever the regions hold.
                  at(moreOrder, {
                    type: "section",
                    props: { title: moreFields },
                    children: unplaced,
                  }),
                ]
              : side,
          },
        ],
      };
    },
  };
};
