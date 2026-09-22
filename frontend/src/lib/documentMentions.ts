/**
 * Who a document mentions.
 *
 * Pulled out of the plugin so the walk over a document can be tested, the way
 * `documentReferences` is. A mention carries an id and nothing else about the
 * person, so the page asks who they all are together rather than each chip
 * asking for itself.
 */

import type { EditorState, LexicalNode } from "lexical";

import { $isMentionNode } from "@/components/ui/editor/nodes/mention-node";

/** Every person named in a set of nodes, sorted so the same page asks the same
 *  question however its nodes are ordered. */
export const collectMentionedUserIds = (nodes: Iterable<LexicalNode>): number[] => {
  const found = new Set<number>();
  for (const node of nodes) {
    if (!$isMentionNode(node)) continue;
    const userId = node.getMentionUserId();
    // A mention written against nobody — pasted, or from before ids were
    // stored — names no one to ask about.
    if (userId !== null) found.add(userId);
  }
  return [...found].sort((a, b) => a - b);
};

/** Everyone a document mentions, wherever in it they sit. */
export const documentMentionedUserIds = (state: EditorState): number[] =>
  state.read(() => collectMentionedUserIds(state._nodeMap.values()));
