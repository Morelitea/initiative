import { createFileRoute } from "@tanstack/react-router";

import { redirectToActiveGuild } from "@/lib/routeGuards";

// See projects.tsx: documents live inside an initiative, so a bare /documents
// forwards to the guild home showing documents.
export const Route = createFileRoute("/_serverRequired/_authenticated/documents")({
  beforeLoad: redirectToActiveGuild("/g/$guildId/", { tool: "documents" }),
});
