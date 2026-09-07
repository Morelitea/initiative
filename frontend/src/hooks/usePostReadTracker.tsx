import type { ReactNode } from "react";
import { createContext, useCallback, useContext, useEffect, useMemo, useRef } from "react";

import { useMarkPostsRead } from "@/hooks/usePosts";

/**
 * How long a notice has to stay on screen before it counts as read.
 *
 * A board is read by scrolling, and flinging past twenty notices is not
 * reading twenty notices. Waiting a beat is the difference between "it went
 * by" and "I looked at it".
 */
const DWELL_MS = 1_000;

/** How long the batch waits for more ids before sending. */
const FLUSH_MS = 1_500;

/** The server's own ceiling on one request; see ``MAX_READ_MARKS``. */
const MAX_PER_REQUEST = 200;

interface PostReadTracker {
  /** A card reports itself once it has been on screen long enough. */
  report: (postId: number) => void;
  /** Called when somebody marks a post unread, so the card they are still
   *  looking at does not immediately mark itself read again. */
  suppress: (postId: number) => void;
}

const noop = () => {};
const PostReadTrackerContext = createContext<PostReadTracker>({ report: noop, suppress: noop });

/**
 * Turning "this was on screen" into "this has been read".
 *
 * Cards do not each POST for themselves — a page of five that grows as you
 * scroll would be a request per card. They report here, and the batch goes out
 * once nothing new has arrived for a moment.
 *
 * The suppression list is what makes *mark unread* stick. The card is still on
 * screen when you click it, so without this the observer would mark it read
 * again a second later and the button would look broken. It holds for as long
 * as the board is mounted: come back to it later and reading it counts again.
 */
export function PostReadTrackerProvider({ children }: { children: ReactNode }) {
  const pending = useRef<Set<number>>(new Set());
  const suppressed = useRef<Set<number>>(new Set());
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const markRead = useMarkPostsRead();
  // The mutation identity changes between renders; the flush reads the latest
  // through a ref so the callbacks below can stay stable.
  const markReadRef = useRef(markRead);
  markReadRef.current = markRead;

  const flush = useCallback(() => {
    timer.current = null;
    const ids = [...pending.current].slice(0, MAX_PER_REQUEST);
    if (ids.length === 0) return;
    for (const id of ids) pending.current.delete(id);
    markReadRef.current.mutate({ post_ids: ids });
  }, []);

  const report = useCallback(
    (postId: number) => {
      if (suppressed.current.has(postId)) return;
      pending.current.add(postId);
      if (timer.current !== null) clearTimeout(timer.current);
      timer.current = setTimeout(flush, FLUSH_MS);
    },
    [flush]
  );

  const suppress = useCallback((postId: number) => {
    suppressed.current.add(postId);
    pending.current.delete(postId);
  }, []);

  // Leaving the board should not lose what was read on it.
  useEffect(
    () => () => {
      if (timer.current !== null) clearTimeout(timer.current);
      flush();
    },
    [flush]
  );

  const value = useMemo(() => ({ report, suppress }), [report, suppress]);
  return (
    <PostReadTrackerContext.Provider value={value}>{children}</PostReadTrackerContext.Provider>
  );
}

export const usePostReadTracker = () => useContext(PostReadTrackerContext);

/**
 * Watch one card, and report it once it has been on screen for {@link DWELL_MS}.
 *
 * Returns the ref to hang on the card. Does nothing for a notice already read,
 * so a board of read notices observes nothing at all.
 */
export function useMarkReadOnScreen(postId: number, alreadyRead: boolean) {
  const { report } = usePostReadTracker();
  const ref = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const element = ref.current;
    if (!element || alreadyRead) return;
    if (typeof IntersectionObserver === "undefined") return;

    let dwell: ReturnType<typeof setTimeout> | null = null;
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          dwell ??= setTimeout(() => report(postId), DWELL_MS);
          return;
        }
        // Scrolled away before the beat was up: it went by, it was not read.
        if (dwell !== null) {
          clearTimeout(dwell);
          dwell = null;
        }
      },
      // Half of it, so a notice taller than the window still counts.
      { threshold: 0.5 }
    );
    observer.observe(element);
    return () => {
      if (dwell !== null) clearTimeout(dwell);
      observer.disconnect();
    };
  }, [postId, alreadyRead, report]);

  return ref;
}
