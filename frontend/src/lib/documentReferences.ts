/**
 * What a document refers to.
 *
 * Chips and links are both references, and the page reads them together: a chip
 * asks `task:12:status`, a link asks `task:12`, and one request answers both.
 * Pulled out of the plugin so the walk over a document can be tested.
 */

import type { EditorState, LexicalNode } from "lexical";

import { $isEntityMentionNode } from "@/components/ui/editor/nodes/entity-mention-node";
import { $isSmartChipNode } from "@/components/ui/editor/nodes/smart-chip-node";
import { chipEntityType, referenceRef } from "@/lib/smartChips";

/** The references a node needs read, or empty if it refers to nothing.
 *
 * A chip asks two questions about the same thing: the fact it shows, and what
 * that thing is called — the reading goes in the sentence and the name goes on
 * the card behind it. Both are the same request. */
export const nodeReferences = (node: LexicalNode): string[] => {
  if ($isSmartChipNode(node)) {
    const kind = node.getChipKind();
    return [node.getRef(), referenceRef(chipEntityType(kind), node.getEntityId())];
  }
  if ($isEntityMentionNode(node)) {
    return [referenceRef(node.getEntityType(), node.getEntityId())];
  }
  return [];
};

/** Every reference in a set of nodes, sorted so the same page asks the same
 *  question however its nodes are ordered. */
export const collectReferences = (nodes: Iterable<LexicalNode>): string[] => {
  const found = new Set<string>();
  for (const node of nodes) {
    for (const ref of nodeReferences(node)) found.add(ref);
  }
  return [...found].sort();
};

/** Every reference a document holds, wherever in it they sit. */
export const documentReferences = (state: EditorState): string[] =>
  state.read(() => collectReferences(state._nodeMap.values()));
