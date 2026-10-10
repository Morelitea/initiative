/**
 * The view editor's changes, kept apart from what is saved: a tree edited by
 * path, and the set of views with every change since it was opened, to undo
 * and redo.
 */

import type {
  CardPartInput,
  ToolViewWrite,
  ViewDefinitionInput,
} from "@/api/generated/initiativeAPI.schemas";

import type { FieldDef } from "./fields";
import { TASK_CARD, TASK_COLUMNS } from "./tasks";
import type { ViewNode } from "./tree";

/** A view's card: its own, or the shipped one. */
export const cardOf = (definition: ViewDefinitionInput): ViewNode =>
  (definition.card as ViewNode | null | undefined) ?? TASK_CARD;

export const withCard = (definition: ViewDefinitionInput, card: ViewNode): ViewDefinitionInput => ({
  ...definition,
  card: card as CardPartInput,
});

/** A view's table columns, as field ids in order: its own, or the shipped ones. */
export const columnsOf = (definition: ViewDefinitionInput): string[] =>
  definition.columns ?? TASK_COLUMNS;

/** How a view names a field when it is stored: a property by its definition
 *  id, which survives a rename, and any other field by its own id. */
export const fieldRef = (field: FieldDef): string =>
  field.propertyId === undefined ? field.id : `property:${field.propertyId}`;

/** Where a node is in a tree: the child it is at each level below the root. */
export type NodePath = readonly number[];

/** A path as a key, the root's being "". */
export const pathKey = (path: NodePath): string => path.join(".");

export const pathOf = (key: string): NodePath => (key === "" ? [] : key.split(".").map(Number));

export const nodeAt = (root: ViewNode, path: NodePath): ViewNode | undefined =>
  path.reduce<ViewNode | undefined>((node, index) => node?.children?.[index], root);

/** `root` with the node at `path` changed by `change`, or taken out where it
 *  answers null. Every node off the path is the one it was. */
export const changeAt = (
  root: ViewNode,
  path: NodePath,
  change: (node: ViewNode) => ViewNode | null
): ViewNode => {
  if (path.length === 0) return change(root) ?? root;
  const [index, ...rest] = path;
  const children = [...(root.children ?? [])];
  const child = children[index];
  if (!child) return root;
  const changed = rest.length === 0 ? change(child) : changeAt(child, rest, change);
  if (changed === null) children.splice(index, 1);
  else children[index] = changed;
  return { ...root, children };
};

/** `root` with `node` among the children of the node at `parent`, at `index`
 *  or last. */
export const insertAt = (
  root: ViewNode,
  parent: NodePath,
  node: ViewNode,
  index?: number
): ViewNode =>
  changeAt(root, parent, (holder) => {
    const children = [...(holder.children ?? [])];
    children.splice(index ?? children.length, 0, node);
    return { ...holder, children };
  });

/** `root` with a child of the node at `parent` moved from `from` to `to`. */
export const moveWithin = (root: ViewNode, parent: NodePath, from: number, to: number): ViewNode =>
  changeAt(root, parent, (holder) => {
    const children = [...(holder.children ?? [])];
    const [moved] = children.splice(from, 1);
    if (moved) children.splice(to, 0, moved);
    return { ...holder, children };
  });

/** Every node of a tree by its path key, for the canvas to find the part a
 *  click landed on. Keyed by the node itself, so a tree drawn twice (a card
 *  on every task) names each part once. */
export const indexPaths = (root: ViewNode): WeakMap<ViewNode, string> => {
  const paths = new WeakMap<ViewNode, string>();
  const walk = (node: ViewNode, path: number[]) => {
    paths.set(node, pathKey(path));
    node.children?.forEach((child, index) => walk(child, [...path, index]));
  };
  walk(root, []);
  return paths;
};

/** A set of views being edited, with what was done to it. */
export type History = {
  past: ToolViewWrite[][];
  present: ToolViewWrite[];
  future: ToolViewWrite[][];
};

export type HistoryAction =
  | { type: "change"; views: ToolViewWrite[] }
  | { type: "undo" }
  | { type: "redo" }
  | { type: "reset"; views: ToolViewWrite[] };

export const startHistory = (views: ToolViewWrite[]): History => ({
  past: [],
  present: views,
  future: [],
});

export const historyReducer = (history: History, action: HistoryAction): History => {
  switch (action.type) {
    case "change":
      return { past: [...history.past, history.present], present: action.views, future: [] };
    case "undo": {
      const previous = history.past.at(-1);
      if (!previous) return history;
      return {
        past: history.past.slice(0, -1),
        present: previous,
        future: [history.present, ...history.future],
      };
    }
    case "redo": {
      const [next, ...future] = history.future;
      if (!next) return history;
      return { past: [...history.past, history.present], present: next, future };
    }
    case "reset":
      return startHistory(action.views);
  }
};
