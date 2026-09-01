import { createFileRoute } from "@tanstack/react-router";

import { redirectToActiveGuild } from "@/lib/routeGuards";

// The initiatives list is the guild home page now, so this legacy address goes
// straight there rather than chaining through the retired `/i` list route.
export const Route = createFileRoute("/_serverRequired/_authenticated/initiatives")({
  beforeLoad: redirectToActiveGuild("/c/$guildId"),
});
