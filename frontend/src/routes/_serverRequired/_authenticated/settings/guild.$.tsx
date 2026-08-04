import { createFileRoute, redirect } from "@tanstack/react-router";

import { guildPath } from "@/lib/guildUrl";

/**
 * Catch-all for the legacy /settings/guild/* URLs. Forwards every subpath
 * (and the bare /settings/guild) to the active guild's settings, so old
 * bookmarks and notification links keep working. No active guild → home.
 */
export const Route = createFileRoute("/_serverRequired/_authenticated/settings/guild/$")({
  beforeLoad: ({ context, params }) => {
    const guildId = context.guilds?.activeGuildId;
    if (!guildId) {
      throw redirect({ to: "/" });
    }
    const splat = params._splat ?? "";
    // The Export tab merged into the Data tab, so forward its legacy path
    // straight to /settings/data (the canonical /settings/export route is
    // itself only a redirect to /settings/data).
    const subPath =
      splat === "export" ? "/settings/data" : splat ? `/settings/${splat}` : "/settings";
    throw redirect({ to: guildPath(guildId, subPath) });
  },
});
