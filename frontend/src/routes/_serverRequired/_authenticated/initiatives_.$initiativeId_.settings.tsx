import { createFileRoute, redirect } from "@tanstack/react-router";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/initiatives_/$initiativeId_/settings"
)({
  beforeLoad: ({ context, params }) => {
    const guildId = context.guilds?.activeGuildId;
    if (guildId) {
      throw redirect({
        to: "/g/$guildId/initiatives/$initiativeId/settings",
        params: { guildId: String(guildId), initiativeId: params.initiativeId },
      });
    }
    throw redirect({ to: "/" });
  },
});
