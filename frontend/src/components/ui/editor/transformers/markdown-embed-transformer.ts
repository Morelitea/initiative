import type { ElementTransformer } from "@lexical/markdown";

import {
  $createReferenceEmbedNode,
  $isReferenceEmbedNode,
  ReferenceEmbedNode,
} from "@/components/ui/editor/nodes/reference-embed-node";
import { isSearchEntityType } from "@/lib/entityResolver";

/**
 * `![[ ]]` in markdown: the embed as Obsidian writes one, with the reference
 * it names ahead of a `|` and the name it had after — `![[task:12|Roll call]]`.
 * The name is what a reader of the raw text sees; the reference is what comes
 * back live.
 */
export const EMBED: ElementTransformer = {
  dependencies: [ReferenceEmbedNode],
  export: (node) => {
    if (!$isReferenceEmbedNode(node)) return null;
    // The name sits between `|` and `]]`, so neither can be in it.
    const name = node.getTextContent().replace(/[|\]]/g, "");
    return `![[${node.getEntityType()}:${node.getEntityId()}|${name}]]`;
  },
  regExp: /^!\[\[([a-z_]+):(\d+)(?:\|([^\]]*))?\]\]\s?$/,
  replace: (parentNode, _children, match) => {
    const [, entityType, entityId, name] = match;
    if (!isSearchEntityType(entityType)) return false;
    parentNode.replace($createReferenceEmbedNode(entityType, Number(entityId), name ?? ""));
  },
  type: "element",
};
