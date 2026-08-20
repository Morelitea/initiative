import { createFileRoute } from "@tanstack/react-router";

import { redirectToActiveGuild } from "@/lib/routeGuards";

// Projects are addressed inside their initiative now, so there is no guild-wide
// project page to forward to — the guild home showing projects is the nearest
// thing a bare /projects can mean.
export const Route = createFileRoute("/_serverRequired/_authenticated/projects")({
  beforeLoad: redirectToActiveGuild("/g/$guildId/", { tool: "projects" }),
});
