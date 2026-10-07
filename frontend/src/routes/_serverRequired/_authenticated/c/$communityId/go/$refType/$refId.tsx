import { createFileRoute, redirect } from "@tanstack/react-router";

import { communityPath } from "@/lib/communityUrl";
import { resolveEntityPath } from "@/lib/entityResolver";

/**
 * Resolve a bare entity reference to the URL that addresses it.
 *
 * A tool entity's address names its initiative, and a few callers hold only an
 * id — a `@mention` in comment text, a queue item's linked entity, a stored
 * notification target. They link here; the loader reads the entity, works out
 * where it lives, and redirects before anything renders, keeping the query
 * (an event's `occurrence`).
 */
export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/go/$refType/$refId"
)({
  loader: async ({ context, params, location }) => {
    const communityId = Number(params.communityId);
    const path = await resolveEntityPath(
      context.queryClient,
      communityId,
      params.refType,
      Number(params.refId)
    );
    // Unresolvable — deleted, or not visible to this reader. The community home is
    // the honest landing spot; guessing at an address would 404 instead.
    throw redirect({
      to: communityPath(communityId, path ?? "/"),
      search: path ? location.search : {},
      replace: true,
    });
  },
});
