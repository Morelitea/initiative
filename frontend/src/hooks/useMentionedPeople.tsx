/**
 * Everyone a page mentions, resolved once.
 *
 * A mention stores an id and the name the writer saw. What a reader should see
 * is who that id is *now* — and a mention needs more than a name to be a link:
 * the handle a profile is addressed by is the username and the number
 * together, neither of which is written into the mention.
 *
 * So the page collects its ids and asks for them in one request, the way
 * `SmartChipScope` does for the things a page refers to. A thread of forty
 * comments naming the same three people asks about three people, once.
 */

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
import { useUserSearch } from "@/hooks/useUsers";

/** How many mentioned people one page resolves at once — the search's ceiling. */
export const MAX_MENTIONED_PEOPLE = 100;

interface MentionedPeopleValue {
  /** Who each mentioned id is, for the ones that came back. */
  people: Map<number, UserSummary>;
  /** Whether the answer has arrived. Until it has, a mention shows the name it
   *  was written with rather than flickering. */
  ready: boolean;
  /** How a page says who it mentions. */
  report: (ids: number[]) => void;
}

const MentionedPeopleContext = createContext<MentionedPeopleValue>({
  people: new Map(),
  ready: false,
  report: () => {},
});

/**
 * The page's answers, above whatever renders the mentions.
 *
 * Mount it **outside** an editor rather than among its plugins: mentions are
 * Lexical decorators, which the composer renders as portals of its own, so a
 * provider inside the composer is not an ancestor of any of them.
 */
export function MentionedPeopleScope({ children }: { children: ReactNode }) {
  const [ids, setIds] = useState<number[]>([]);

  const report = useCallback((next: number[]) => {
    // Compared as a string so an edit that moves a mention without changing
    // the set does not start a new request.
    setIds((current) => (current.join() === next.join() ? current : next));
  }, []);

  const asked = ids.slice(0, MAX_MENTIONED_PEOPLE);
  const query = useUserSearch({
    userIds: asked,
    pageSize: MAX_MENTIONED_PEOPLE,
    enabled: asked.length > 0,
  });

  const items = query.data?.items;
  const isFetched = query.isFetched;
  const value = useMemo<MentionedPeopleValue>(() => {
    const people = new Map<number, UserSummary>();
    for (const member of items ?? []) people.set(member.id, member);
    return { people, ready: asked.length === 0 || isFetched, report };
  }, [items, isFetched, asked.length, report]);

  return (
    <MentionedPeopleContext.Provider value={value}>{children}</MentionedPeopleContext.Provider>
  );
}

/** How something inside the page hands its ids up. */
export const useReportMentionedPeople = () => useContext(MentionedPeopleContext).report;

/**
 * Reports a set of ids the caller already holds.
 *
 * A component rather than a hook on the parent, because the parent is the
 * scope's own parent and cannot reach into it. Markdown bodies take this route;
 * an editor uses `useReportMentionedPeople` from a plugin, which has to walk
 * the document first.
 */
export function ReportMentionedPeople({ ids }: { ids: number[] }): null {
  const report = useReportMentionedPeople();
  // Keyed on the values so a fresh array with the same ids does not re-report.
  const key = ids.join();

  useEffect(() => {
    report(key ? key.split(",").map(Number) : []);
  }, [key, report]);

  return null;
}

/** Who a mentioned id is, or `undefined` while the answer is on its way — and
 *  for good where they cannot be read. */
export const useMentionedPerson = (userId: number | null | undefined): UserSummary | undefined =>
  useContext(MentionedPeopleContext).people.get(userId ?? Number.NaN);
