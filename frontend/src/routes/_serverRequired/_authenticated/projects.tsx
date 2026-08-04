import { createFileRoute } from "@tanstack/react-router";

import { redirectToActiveGuild } from "@/lib/routeGuards";
import { validateToolListSearch } from "@/lib/routeSearch";

export const Route = createFileRoute("/_serverRequired/_authenticated/projects")({
  validateSearch: validateToolListSearch,
  beforeLoad: redirectToActiveGuild("/g/$guildId/projects"),
});
