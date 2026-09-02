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
  loader: async ({ context, deps }) => {
    const { queryClient } = context;
    // Keys and params come from the same helper the page's own queries use, so
    // the prefetch warms them rather than sitting beside them under another key.
    const { sections, favorites } = contactsPrefetch(deps.q ?? "");
    try {
      await Promise.all([
        queryClient.ensureQueryData({ ...sections, staleTime: 30_000 }),
        queryClient.ensureQueryData({ ...favorites, staleTime: 30_000 }),
      ]);
    } catch {
      // Silently fail — the component fetches its own data.
    }
  },
  component: lazyRouteComponent(() =>
    import("@/pages/user/MyContactsPage").then((m) => ({ default: m.MyContactsPage }))
  ),
});
