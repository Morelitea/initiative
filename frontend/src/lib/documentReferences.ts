/**
 * What a document refers to.
 *
 * Chips and links are both references, and the page reads them together: a chip
 * asks `task:12:status`, a link asks `task:12`, and one request answers both.
 * Pulled out of the plugin so the walk can be tested without an editor.
 */

import type { LexicalNode } from "lexical";

import { $isBadgeNode } from "@/components/ui/editor/nodes/badge-node";
import { $isEntityMentionNode } from "@/components/ui/editor/nodes/entity-mention-node";
import { referenceRef } from "@/lib/badges";

/** The reference a node needs read, or `null` if it refers to nothing. */
export const nodeReference = (node: LexicalNode): string | null => {
  if ($isBadgeNode(node)) return node.getRef();
  if ($isEntityMentionNode(node)) {
    return referenceRef(node.getEntityType(), node.getEntityId());
  }
  return null;
};

/** Every reference in a set of nodes, sorted so the same page asks the same
 *  question however its nodes are ordered. */
export const collectReferences = (nodes: Iterable<LexicalNode>): string[] => {
  const found = new Set<string>();
  for (const node of nodes) {
    const ref = nodeReference(node);
    if (ref) found.add(ref);
  }
  return [...found].sort();
};
