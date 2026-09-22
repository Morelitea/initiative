import { createContext, type ReactNode, useContext, useMemo } from "react";

import { MentionedPeopleScope, ReportMentionedPeople } from "@/hooks/useMentionedPeople";
import { useSmartChipStates } from "@/hooks/useSmartChips";
import { collectCommentReferences } from "@/lib/commentReferences";

interface Resolved {
  /** Current names by `kind:id`. */
  titles: Map<string, string>;
  /** Whether the answer has arrived. Until it has, a comment shows the words
   *  it was written with rather than flickering. */
  ready: boolean;
}

const CommentReferencesContext = createContext<Resolved>({
  titles: new Map(),
  ready: false,
});

export const useCommentReferences = () => useContext(CommentReferencesContext);

/**
 * Resolves everything a thread refers to, once.
 *
 * A thread of forty comments naming the same task asks about it once, and a
 * rename reaches all forty without any of them being edited.
 *
 * The people it names are resolved the same way, but by `MentionedPeopleScope`
 * — the same scope a document's mentions read from, so a mention is the same
 * chip wherever it is written.
 */
export function CommentReferences({
  contents,
  children,
}: {
  contents: string[];
  children: ReactNode;
}) {
  const { refs, userIds } = useMemo(() => collectCommentReferences(contents), [contents]);

  const chips = useSmartChipStates(refs, refs.length > 0);

  const value = useMemo<Resolved>(() => {
    const titles = new Map<string, string>();
    for (const state of chips.data?.items ?? []) {
      if (state.text) titles.set(state.ref, state.text);
    }
    return { titles, ready: refs.length === 0 || chips.isFetched };
  }, [chips.data, chips.isFetched, refs.length]);

  return (
    <CommentReferencesContext.Provider value={value}>
      <MentionedPeopleScope>
        <ReportMentionedPeople ids={userIds} />
        {children}
      </MentionedPeopleScope>
    </CommentReferencesContext.Provider>
  );
}
