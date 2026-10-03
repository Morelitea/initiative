import { useEffect, useMemo, useState } from "react";

import { UNTAGGED_PATH } from "@/components/tags/TagTreeView";
import { useTags } from "@/hooks/useTags";
import { buildTagTree, collectDescendantTagIds, findNodeByPath } from "@/lib/tagTree";

/**
 * What a tag tree has picked out, for a list browsed by tag.
 *
 * A click picks one tag, or drops it if it was the only one; Ctrl/Cmd+click
 * adds or removes one. A picked tag stands for itself and everything under it,
 * so `tagIds` is what the list's `tag_ids` filter takes. The pick is cleared
 * whenever the tags view is left.
 */
export const useTagTreeSelection = (active: boolean) => {
  const { data: allTags = [] } = useTags();
  const [selectedPaths, setSelectedPaths] = useState<Set<string>>(new Set());

  useEffect(() => {
    if (!active) setSelectedPaths(new Set());
  }, [active]);

  const toggle = (fullPath: string, ctrlKey: boolean) => {
    setSelectedPaths((prev) => {
      const next = new Set(prev);
      if (ctrlKey) {
        if (next.has(fullPath)) next.delete(fullPath);
        else next.add(fullPath);
      } else if (next.size === 1 && next.has(fullPath)) {
        next.clear();
      } else {
        next.clear();
        next.add(fullPath);
      }
      return next;
    });
  };

  const tagIds = useMemo(() => {
    if (!active || selectedPaths.size === 0) return [];
    const tree = buildTagTree(allTags);
    const ids: number[] = [];
    for (const path of selectedPaths) {
      if (path === UNTAGGED_PATH) continue;
      const node = findNodeByPath(tree, path);
      if (node) ids.push(...collectDescendantTagIds(node));
    }
    return ids;
  }, [active, selectedPaths, allTags]);

  return {
    allTags,
    selectedPaths,
    toggle,
    tagIds,
    wantsUntagged: active && selectedPaths.has(UNTAGGED_PATH),
  };
};
