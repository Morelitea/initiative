import { createFileRoute } from "@tanstack/react-router";

import { redirectToActiveGuild } from "@/lib/routeGuards";
import { validateToolListSearchWithPage } from "@/lib/routeSearch";

export const Route = createFileRoute("/_serverRequired/_authenticated/documents")({
  validateSearch: validateToolListSearchWithPage,
  beforeLoad: redirectToActiveGuild("/g/$guildId/documents"),
});
