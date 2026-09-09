import { QueryClient } from "@tanstack/react-query";

/**
 * How long an answer is trusted before it is worth asking again.
 *
 * This is not how fresh the screen is — guild content is kept current by the
 * realtime bus (`useRealtimeUpdates`), which invalidates by id the moment
 * somebody writes, and by the mutation helpers in `api/query-keys`. Both
 * refetch regardless of this window. What it governs is the duplicate
 * fetching nothing asked for: a remount, a route stepped back to, a tab
 * brought forward.
 *
 * Thirty seconds is the number the route loaders and data hooks already pass
 * one at a time, so this makes their common case the default rather than a
 * thing each new caller has to remember.
 */
const DEFAULT_STALE_TIME_MS = 30_000;

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // Coming back to a tab refetches whatever has aged past the window
      // above. The socket only delivers while it is open, and only to the
      // initiative rooms it joined at connect time — a tab that was in the
      // background, or on a machine that slept, has nothing else that would
      // tell it what changed while it was away.
      refetchOnWindowFocus: true,
      staleTime: DEFAULT_STALE_TIME_MS,
      retry: 1,
      placeholderData: (prev: unknown) => prev,
    },
  },
});
