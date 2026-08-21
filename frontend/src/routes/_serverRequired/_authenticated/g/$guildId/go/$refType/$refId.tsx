import { createFileRoute, redirect } from "@tanstack/react-router";

import { resolveEntityPath } from "@/lib/entityResolver";
import { guildPath } from "@/lib/guildUrl";

/**
 * Resolve a bare entity reference to the URL that addresses it.
 *
 * A tool entity's address names its initiative, and a few callers hold only an
 * id — a `@mention` in comment text, a queue item's linked entity, a stored
 * notification target. They link here; the loader reads the entity, works out
 * where it lives, and redirects before anything renders.
 */
export const Route = createFileRoute(
  "/_serverRequired/_authenticated/g/$guildId/go/$refType/$refId"
)({
  loader: async ({ context, params }) => {
    const guildId = Number(params.guildId);
    const path = await resolveEntityPath(
      context.queryClient,
      guildId,
      params.refType,
      Number(params.refId)
    );
    // Unresolvable — deleted, or not visible to this reader. The guild home is
    // the honest landing spot; guessing at an address would 404 instead.
    throw redirect({ to: guildPath(guildId, path ?? "/"), replace: true });
  },
});
