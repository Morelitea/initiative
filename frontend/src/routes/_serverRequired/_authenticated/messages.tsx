import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

/**
 * Who the page should open a conversation with, as a URL handle —
 * `/messages?with=jordan1234`. It is what a contacts row links to, so somebody
 * you have never messaged is reachable in one click and the page decides what
 * that means: an open channel, or an offer to ask for one.
 */
interface MessagesSearch {
  with?: string;
}

export const Route = createFileRoute("/_serverRequired/_authenticated/messages")({
  validateSearch: (search: Record<string, unknown>): MessagesSearch => {
    const handle = typeof search.with === "string" ? search.with.trim() : "";
    return handle ? { with: handle } : {};
  },
  // No loader: a thread is read out of this device's own store, which the page
  // itself unlocks. There is nothing for the router to prefetch.
  component: lazyRouteComponent(() =>
    import("@/pages/user/MyMessagesPage").then((m) => ({
      default: m.MyMessagesPage,
    }))
  ),
});
