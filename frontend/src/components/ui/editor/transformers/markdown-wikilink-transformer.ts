import type { TextMatchTransformer } from "@lexical/markdown";

import {
  $createWikilinkNode,
  $isWikilinkNode,
  WikilinkNode,
} from "@/components/ui/editor/nodes/wikilink-node";

export const WIKILINK: TextMatchTransformer = {
  dependencies: [WikilinkNode],
  export: (node) => {
    if (!$isWikilinkNode(node)) {
      return null;
    }
    const title = node.getDocumentTitle();
    const id = node.getDocumentId();
    // Format: [[Title|id]] for resolved links, [[Title]] for unresolved
    if (id !== null) {
      return `[[${title}|${id}]]`;
    }
    return `[[${title}]]`;
  },
  // Import pattern: matches [[Title]] or [[Title|id]]
  importRegExp: /\[\[([^\]|]+)(?:\|(\d+))?\]\]/,
  // Typing pattern: matches when user types [[Something]] and ends with ]]
  // This should only fire after the closing brackets are typed
  // Note: This won't match the |id format since users type via typeahead
  regExp: /\[\[([^\]|]+)(?:\|(\d+))?\]\]$/,
  replace: (textNode, match) => {
    const [, documentTitle, documentIdStr] = match;
    if (!documentTitle) {
      return;
    }
    const documentId = documentIdStr ? parseInt(documentIdStr, 10) : null;
    const wikilinkNode = $createWikilinkNode(documentTitle.trim(), documentId);
    textNode.replace(wikilinkNode);
  },
  trigger: "]",
  type: "text-match",
};
