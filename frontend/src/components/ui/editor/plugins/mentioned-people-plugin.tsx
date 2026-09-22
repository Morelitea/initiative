import { useLexicalComposerContext } from "@lexical/react/LexicalComposerContext";
import { useEffect } from "react";

import { useReportMentionedPeople } from "@/hooks/useMentionedPeople";
import { documentMentionedUserIds } from "@/lib/documentMentions";

/**
 * Tells the surrounding `MentionedPeopleScope` who this document mentions.
 *
 * Mentions do not fetch for themselves — a document naming the same person
 * six times would be six requests. This walks the editor for their ids and
 * hands the set up; the scope asks about them together and hands the answers
 * back down. A mention added or deleted changes the set, which is why it
 * re-collects on every update rather than only on mount.
 */
export function MentionedPeoplePlugin(): null {
  const [editor] = useLexicalComposerContext();
  const report = useReportMentionedPeople();

  useEffect(() => {
    const collect = () => report(documentMentionedUserIds(editor.getEditorState()));
    collect();
    return editor.registerUpdateListener(collect);
  }, [editor, report]);

  return null;
}
