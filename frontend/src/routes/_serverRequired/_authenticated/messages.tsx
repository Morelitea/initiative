import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute("/_serverRequired/_authenticated/messages")({
  // No loader: a thread is read out of this device's own store, which the page
  // itself unlocks. There is nothing for the router to prefetch.
  component: lazyRouteComponent(() =>
    import("@/pages/user/MyMessagesPage").then((m) => ({
      default: m.MyMessagesPage,
    }))
  ),
});
