import type { SerializedEditorState, SerializedLexicalNode } from "lexical";

interface SerializedMentionNode extends SerializedLexicalNode {
  type: "mention";
  mentionUserId?: number | null;
}

function isMentionNode(node: SerializedLexicalNode): node is SerializedMentionNode {
  return node.type === "mention";
}

function traverseNodes(
  nodes: SerializedLexicalNode[],
  callback: (node: SerializedLexicalNode) => void
): void {
  for (const node of nodes) {
    callback(node);
    if ("children" in node && Array.isArray(node.children)) {
      traverseNodes(node.children as SerializedLexicalNode[], callback);
    }
  }
}

export function extractMentionUserIds(content: SerializedEditorState | null | undefined): number[] {
  if (!content?.root?.children) {
    return [];
  }
  const userIds: number[] = [];
  traverseNodes(content.root.children as SerializedLexicalNode[], (node) => {
    if (isMentionNode(node) && typeof node.mentionUserId === "number") {
      userIds.push(node.mentionUserId);
    }
  });
  return [...new Set(userIds)];
}

export function findNewMentions(
  oldContent: SerializedEditorState | null | undefined,
  newContent: SerializedEditorState | null | undefined
): number[] {
  const oldMentionIds = new Set(extractMentionUserIds(oldContent));
  const newMentionIds = extractMentionUserIds(newContent);
  return newMentionIds.filter((id) => !oldMentionIds.has(id));
}
