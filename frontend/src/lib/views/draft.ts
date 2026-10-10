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

const nodesIn = (node: ViewNode): ViewNode[] => [node, ...(node.children ?? []).flatMap(nodesIn)];

/** Whether a part can be taken off the card: not one that is, or holds, a
 *  field every card shows (its title, which opens the task). */
export const removable = (node: ViewNode, fields: ReadonlyMap<string, FieldDef>): boolean =>
  !nodesIn(node).some(
    (each) => each.type === "field" && fields.get(String(each.props?.field))?.hideable === false
  );

/** The built-in fields a table draws as a column. */
const TABLE_BUILTINS = new Set(TASK_COLUMNS);

/** The fields a view can still add: a card's not on it (and no property alone
 *  where it shows them all), a table's not among its columns and drawn as
 *  one. */
export const addableFields = (
  definition: ViewDefinitionInput,
  fields: ReadonlyMap<string, FieldDef>
): FieldDef[] => {
  const all = [...fields.values()];
  if (definition.layout.type === "board") {
    const card = cardOf(definition);
    const named = new Set(
      nodesIn(card).flatMap((node) => (node.type === "field" ? [String(node.props?.field)] : []))
    );
    const showsProperties = nodesIn(card).some((node) => node.type === "properties");
    return all.filter(
      (field) => !named.has(field.id) && !(showsProperties && field.source === "property")
    );
  }
  if (definition.layout.type === "table") {
    const columns = new Set(columnsOf(definition));
    return all.filter(
      (field) =>
        !columns.has(field.id) && (field.source !== "builtin" || TABLE_BUILTINS.has(field.id))
    );
  }
  return [];
};

/** Whether a card shows every property, as a part of its own. */
export const showsAllProperties = (card: ViewNode): boolean =>
  nodesIn(card).some((node) => node.type === "properties");

/** What the editor has selected: the view itself, a part of its card by
 *  path, or one of its table's columns by field. */
export type Selection =
  | { kind: "view" }
  | { kind: "part"; path: NodePath }
  | { kind: "column"; field: string };

export const VIEW_SELECTED: Selection = { kind: "view" };

export const sameSelection = (a: Selection, b: Selection): boolean =>
  a.kind === b.kind &&
  (a.kind !== "part" || pathKey(a.path) === pathKey((b as { path: NodePath }).path)) &&
  (a.kind !== "column" || a.field === (b as { field: string }).field);

const startsWith = (path: NodePath, prefix: NodePath) =>
  prefix.length <= path.length && prefix.every((index, depth) => path[depth] === index);

/** Where the part at `path` is once a child of `parent` moved from `from` to
 *  `to`: the moved part goes with it, and its siblings between close up. */
export const pathAfterMove = (
  path: NodePath,
  parent: NodePath,
  from: number,
  to: number
): NodePath => {
  if (path.length <= parent.length || !startsWith(path, parent)) return path;
  const index = path[parent.length];
  let next = index;
  if (index === from) next = to;
  else if (from < index && index <= to) next = index - 1;
  else if (to <= index && index < from) next = index + 1;
  return [...parent, next, ...path.slice(parent.length + 1)];
};

/** Where the part at `path` is once the part at `removed` is taken out, or
 *  null when it went with it. */
export const pathAfterRemove = (path: NodePath, removed: NodePath): NodePath | null => {
  if (startsWith(path, removed)) return null;
  const depth = removed.length - 1;
  if (path.length <= depth || !startsWith(path, removed.slice(0, depth))) return path;
  if (path[depth] < removed[depth]) return path;
  return [...path.slice(0, depth), path[depth] - 1, ...path.slice(depth + 1)];
};

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
