/**
 * Everyone a page mentions, resolved once.
 *
 * A mention stores an id and nothing else about the person. What a reader
 * should see is who that id is *now* — and a mention needs more than a name to
 * be a link: the handle a profile is addressed by is the username and the
 * number together, neither of which is written into the mention.
 *
 * So the page collects its ids and asks for them together. A thread of forty
 * comments naming the same three people asks about three people, once.
 */

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";

import type { UserSummary } from "@/api/generated/initiativeAPI.schemas";
import { getSearchUsersQueryKey, searchUsers } from "@/api/generated/users/users";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { USER_ID_LOOKUP_MAX } from "@/hooks/useUsers";
import { collectCommentReferences } from "@/lib/commentReferences";

/** A person is read in the community the mention was written in: that is who
 *  they are there, and whether they are still there at all. */
const personKey = (communityId: number, userId: number) => `${communityId}:${userId}`;

interface MentionedPeopleValue {
  /** Who a mentioned id is in a community — the scope's own unless one is
   *  named — for the ones that came back. */
  find: (userId: number, communityId?: number) => UserSummary | undefined;
  /** Whether every answer has arrived. Until it has, a mention cannot tell
   *  somebody who has left from somebody not yet looked up. */
  ready: boolean;
  /** Whether the lookup gave up, so no answer is coming. */
  failed: boolean;
  /** How a page says who it mentions in a community, the scope's own unless
   *  one is named. Each community's set replaces the one reported before it. */
  report: (ids: number[], communityId?: number) => void;
}

const MentionedPeopleContext = createContext<MentionedPeopleValue>({
  find: () => undefined,
  ready: false,
  failed: false,
  report: () => {},
});

/**
 * The page's answers, above whatever renders the mentions.
 *
 * Mount it **outside** an editor rather than among its plugins: mentions are
 * Lexical decorators, which the composer renders as portals of its own, so a
 * provider inside the composer is not an ancestor of any of them.
 *
 * `communityId` is the community the mentions below were written in, where that is
 * not the one the page is in. A list that spans communities reports each one's
 * people under its own id instead.
 */
export function MentionedPeopleScope({
  communityId: ownCommunityId,
  children,
}: {
  communityId?: number;
  children: ReactNode;
}) {
  const activeCommunityId = useActiveCommunityId();
  const communityId = ownCommunityId ?? activeCommunityId;
  const [asked, setAsked] = useState<Record<number, number[]>>({});

  const report = useCallback(
    (ids: number[], community = communityId) => {
      setAsked((current) => {
        // Compared as a string so an edit that moves a mention without changing
        // the set does not start a new request.
        if ((current[community] ?? []).join() === ids.join()) return current;
        const { [community]: _previous, ...rest } = current;
        return ids.length > 0 ? { ...rest, [community]: ids } : rest;
      });
    },
    [communityId]
  );

  // As many requests as the search's page ceiling takes, all in flight
  // together and answered as one: a page that mentions more people than one
  // request can name still names every one of them.
  const lookups = Object.entries(asked).flatMap(([community, ids]) => {
    const pages: { communityId: number; userIds: number[] }[] = [];
    for (let index = 0; index < ids.length; index += USER_ID_LOOKUP_MAX) {
      pages.push({
        communityId: Number(community),
        userIds: ids.slice(index, index + USER_ID_LOOKUP_MAX),
      });
    }
    return pages;
  });

  const query = useQuery({
    // Under the member search's own address, so whatever refreshes the members
    // refreshes the names they are mentioned by.
    queryKey: [...getSearchUsersQueryKey(communityId), { mentioned: asked }],
    queryFn: async ({ signal }) => {
      const answers = await Promise.all(
        lookups.map(({ communityId: community, userIds }) =>
          searchUsers(
            community,
            { user_id: userIds, page_size: USER_ID_LOOKUP_MAX },
            undefined,
            signal
          ).then((page) =>
            page.items.map((person): [string, UserSummary] => [
              personKey(community, person.id),
              person,
            ])
          )
        )
      );
      return answers.flat();
    },
    enabled: lookups.length > 0,
    staleTime: 30_000,
    // A mention added to the page keeps everyone already named on screen while
    // the new set is asked about.
    placeholderData: keepPreviousData,
  });

  const entries = query.data;
  // An answer to an earlier set, or no answer at all, says nothing about who
  // is missing from this one.
  const ready = lookups.length === 0 || (query.isSuccess && !query.isPlaceholderData);
  const value = useMemo<MentionedPeopleValue>(() => {
    const people = new Map(entries);
    return {
      find: (userId, community = communityId) => people.get(personKey(community, userId)),
      ready,
      failed: query.isError,
      report,
    };
  }, [entries, communityId, ready, query.isError, report]);

  return (
    <MentionedPeopleContext.Provider value={value}>{children}</MentionedPeopleContext.Provider>
  );
}

/** The nearest scope: who its mentions are, and how to tell it about more. */
export const useMentionedPeople = () => useContext(MentionedPeopleContext);

/**
 * Reports the people a set of markdown texts mention.
 *
 * A component rather than a hook on the parent, because the parent is the
 * scope's own parent and cannot reach into it. Markdown bodies and list
 * excerpts take this route; an editor reports from a plugin, which has to walk
 * the document first.
 */
export function ReportMentionedPeople({
  texts,
  communityId,
}: {
  texts: string[];
  /** The community the texts were written in, where a list spans several. */
  communityId?: number;
}): null {
  const { report } = useMentionedPeople();
  // Keyed on the values so a fresh array naming the same people does not
  // re-report.
  const key = collectCommentReferences(texts).userIds.join();

  useEffect(() => {
    report(key ? key.split(",").map(Number) : [], communityId);
    // Gone from the page, it stops asking about anyone.
    return () => report([], communityId);
  }, [key, communityId, report]);

  return null;
}

/** Who a mentioned id is, or `undefined` while the answer is on its way — and
 *  for good once `ready` says it is not coming. */
export const useMentionedPerson = (
  userId: number | null | undefined,
  communityId?: number
): { person: UserSummary | undefined; ready: boolean; failed: boolean } => {
  const { find, ready, failed } = useMentionedPeople();
  return { person: userId == null ? undefined : find(userId, communityId), ready, failed };
};
