import { createFileRoute } from "@tanstack/react-router";

import { redirectToActiveGuild } from "@/lib/routeGuards";

export const Route = createFileRoute("/_serverRequired/_authenticated/initiatives")({
  beforeLoad: redirectToActiveGuild("/g/$guildId/initiatives"),
});
