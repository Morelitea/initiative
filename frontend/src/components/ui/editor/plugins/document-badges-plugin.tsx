import { useLexicalComposerContext } from "@lexical/react/LexicalComposerContext";
import type { JSX, ReactNode } from "react";
import { useEffect, useMemo, useState } from "react";

import type { BadgeState } from "@/api/generated/initiativeAPI.schemas";
import { $isBadgeNode } from "@/components/ui/editor/nodes/badge-node";
import { BadgeStatesContext, useDocumentBadges } from "@/hooks/useDocumentBadges";

/**
 * Reads every chip on the page, once.
 *
 * The chips do not fetch for themselves — thirty badges would be thirty
 * requests. This walks the editor for their references, asks for them together,
 * and hands the answer down. A chip added or deleted changes the set, which is
 * why it re-collects on every update rather than only on mount.
 */
export function DocumentBadgesPlugin({ children }: { children?: ReactNode }): JSX.Element {
  const [editor] = useLexicalComposerContext();
  const [refs, setRefs] = useState<string[]>([]);

  useEffect(() => {
    const collect = () => {
      editor.getEditorState().read(() => {
        const found = new Set<string>();
        for (const node of Object.values(editor.getEditorState()._nodeMap)) {
          if ($isBadgeNode(node)) found.add(node.getRef());
        }
        // Sorted and compared as a string so an edit that moves a badge without
        // changing the set does not start a new request.
        const next = [...found].sort();
        setRefs((current) => (current.join() === next.join() ? current : next));
      });
    };
    collect();
    return editor.registerUpdateListener(collect);
  }, [editor]);

  const { data } = useDocumentBadges(refs);

  const states = useMemo(() => {
    const map = new Map<string, BadgeState>();
    for (const state of data?.items ?? []) map.set(state.ref, state);
    return map;
  }, [data]);

  return <BadgeStatesContext.Provider value={states}>{children}</BadgeStatesContext.Provider>;
}
