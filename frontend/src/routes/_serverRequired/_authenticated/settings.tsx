import { createFileRoute } from "@tanstack/react-router";

import { redirectToActiveGuild } from "@/lib/routeGuards";

export const Route = createFileRoute("/_serverRequired/_authenticated/settings")({
  beforeLoad: (opts) => {
    // Only redirect when we're at exactly /settings, not a child route like
    // /settings/admin. Forward straight to the active guild's settings.
    if (opts.location.pathname === "/settings" || opts.location.pathname === "/settings/") {
      redirectToActiveGuild("/g/$guildId/settings")(opts);
    }
  },
});
