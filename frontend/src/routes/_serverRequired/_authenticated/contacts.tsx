import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

import { contactsPrefetch } from "@/hooks/useContacts";

/** The search term lives in the URL, so a search is linkable and goes back. */
interface ContactsSearch {
  q?: string;
}

export const Route = createFileRoute("/_serverRequired/_authenticated/contacts")({
  validateSearch: (search: Record<string, unknown>): ContactsSearch => {
    const q = typeof search.q === "string" ? search.q.trim() : "";
    return q ? { q } : {};
  },
  loaderDeps: ({ search }) => ({ q: search.q }),
  loader: ({ context, deps }) => {
    const { queryClient } = context;
    // Keys and params come from the same helper the page's own queries use, so
    // the prefetch warms them rather than sitting beside them under another key.
    const { sections, favorites } = contactsPrefetch(deps.q ?? "");
    // Started, not awaited. A term is answered by visiting every community the
    // reader is in, which takes as long as it takes; holding the navigation for
    // it would freeze the page the term was typed on, with nothing to say why.
    // The page owns that wait instead, and says what it is doing.
    // The component fetches its own data and reports its own failure, so a
    // rejection here has nothing left to do.
    void queryClient.ensureQueryData({ ...sections, staleTime: 30_000 }).catch(() => {});
    void queryClient.ensureQueryData({ ...favorites, staleTime: 30_000 }).catch(() => {});
  },
  component: lazyRouteComponent(() =>
    import("@/pages/user/MyContactsPage").then((m) => ({ default: m.MyContactsPage }))
  ),
});
