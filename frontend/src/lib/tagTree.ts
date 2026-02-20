import type { TagSummary } from "@/api/generated/initiativeAPI.schemas";

export interface TagTreeNode {
  segment: string; // The segment name (e.g., "a" for "parent/a")
  fullPath: string; // The full path (e.g., "parent/a")
  tag: TagSummary | null; // The actual tag at this node, if it exists
  children: TagTreeNode[];
}

/**
 * Build a tree structure from a flat list of tags using "/" as the path separator.
 * Intermediate nodes without a matching tag get `tag: null`.
 */
export function buildTagTree(tags: TagSummary[]): TagTreeNode[] {
  const tagsByPath = new Map<string, TagSummary>();
  tags.forEach((tag) => tagsByPath.set(tag.name, tag));

  const root: TagTreeNode[] = [];

  const getOrCreateNode = (
    nodes: TagTreeNode[],
    segment: string,
    currentPath: string
  ): TagTreeNode => {
    let node = nodes.find((n) => n.segment === segment);

    if (!node) {
      node = {
        segment,
        fullPath: currentPath,
        tag: tagsByPath.get(currentPath) ?? null,
        children: [],
      };
      nodes.push(node);
    }

    return node;
  };

  tags.forEach((tag) => {
    const segments = tag.name.split("/");
    let currentNodes = root;
    let currentPath = "";

    segments.forEach((segment, index) => {
      currentPath = index === 0 ? segment : `${currentPath}/${segment}`;
      const node = getOrCreateNode(currentNodes, segment, currentPath);

      if (currentPath === tag.name) {
        node.tag = tag;
      }

      currentNodes = node.children;
    });
  });

  const sortNodes = (nodes: TagTreeNode[]): TagTreeNode[] => {
    return nodes
      .map((node) => ({
        ...node,
        children: sortNodes(node.children),
      }))
      .sort((a, b) => a.segment.localeCompare(b.segment));
  };

  return sortNodes(root);
}

/**
 * Recursively collect all tag IDs under a tree node (including the node itself).
 */
export function collectDescendantTagIds(node: TagTreeNode): Set<number> {
  const ids = new Set<number>();
  if (node.tag) {
    ids.add(node.tag.id);
  }
  for (const child of node.children) {
    for (const id of collectDescendantTagIds(child)) {
      ids.add(id);
    }
  }
  return ids;
}

/**
 * Count documents for a tree node by summing across the node and all its descendants.
 * `docCountByTagId` maps tag ID → number of documents with that tag.
 */
export function countDocumentsForNode(
  node: TagTreeNode,
  docCountByTagId: Map<number, number>
): number {
  let count = 0;
  if (node.tag) {
    count += docCountByTagId.get(node.tag.id) ?? 0;
  }
  for (const child of node.children) {
    count += countDocumentsForNode(child, docCountByTagId);
  }
  return count;
}

/**
 * Find a tree node by its full path.
 */
export function findNodeByPath(nodes: TagTreeNode[], fullPath: string): TagTreeNode | null {
  for (const node of nodes) {
    if (node.fullPath === fullPath) return node;
    const found = findNodeByPath(node.children, fullPath);
    if (found) return found;
  }
  return null;
}
