import { useLexicalComposerContext } from "@lexical/react/LexicalComposerContext";
import { useEffect } from "react";

import { useReportReferences } from "@/hooks/useSmartChips";
import { documentReferences } from "@/lib/documentReferences";

/**
 * Tells the surrounding `SmartChipScope` what this document refers to.
 *
 * Chips and references do not fetch for themselves — thirty of them would be
 * thirty requests. This walks the editor for their references and hands the set
 * up; the scope asks for them together and hands the answers back down. A chip
 * added or deleted changes the set, which is why it re-collects on every update
 * rather than only on mount.
 */
export function SmartChipRefsPlugin(): null {
  const [editor] = useLexicalComposerContext();
  const report = useReportReferences();

  useEffect(() => {
    const collect = () => report(documentReferences(editor.getEditorState()));
    collect();
    return editor.registerUpdateListener(collect);
  }, [editor, report]);

  return null;
}
