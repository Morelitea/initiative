import { createContext, type ReactNode, useContext, useMemo } from "react";

import { useSmartChipStates } from "@/hooks/useSmartChips";
import { useUserSearch } from "@/hooks/useUsers";
import { collectCommentReferences } from "@/lib/commentReferences";
import { getUserDisplayName } from "@/lib/userDisplay";

/** How many mentioned people one thread resolves at once. */
const MAX_PEOPLE = 100;

interface Resolved {
  /** Current names by `kind:id`. */
  titles: Map<string, string>;
  /** Current names by user id. */
  people: Map<number, string>;
  /** Whether the answer has arrived. Until it has, a comment shows the words
   *  it was written with rather than flickering. */
  ready: boolean;
}

const CommentReferencesContext = createContext<Resolved>({
  titles: new Map(),
  people: new Map(),
  ready: false,
});

export const useCommentReferences = () => useContext(CommentReferencesContext);

/**
 * Resolves everything a thread refers to, once.
 *
 * A thread of forty comments naming the same task asks about it once, and a
 * rename reaches all forty without any of them being edited.
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
  const people = useUserSearch({
    userIds: userIds.slice(0, MAX_PEOPLE),
    pageSize: MAX_PEOPLE,
    enabled: userIds.length > 0,
  });

  const value = useMemo<Resolved>(() => {
    const titles = new Map<string, string>();
    for (const state of chips.data?.items ?? []) {
      if (state.text) titles.set(state.ref, state.text);
    }
    const names = new Map<number, string>();
    for (const member of people.data?.items ?? []) {
      names.set(member.id, getUserDisplayName(member));
    }
    return {
      titles,
      people: names,
      ready: (refs.length === 0 || chips.isFetched) && (userIds.length === 0 || people.isFetched),
    };
  }, [chips.data, chips.isFetched, people.data, people.isFetched, refs.length, userIds.length]);

  return (
    <CommentReferencesContext.Provider value={value}>{children}</CommentReferencesContext.Provider>
  );
}
