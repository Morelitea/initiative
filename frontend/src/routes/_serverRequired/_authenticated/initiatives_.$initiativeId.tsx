import { createFileRoute, redirect } from "@tanstack/react-router";

export const Route = createFileRoute("/_serverRequired/_authenticated/initiatives_/$initiativeId")({
  beforeLoad: ({ context, params }) => {
    const guildId = context.guilds?.activeGuildId;
    if (guildId) {
      throw redirect({
        to: "/g/$guildId/initiatives/$initiativeId",
        params: { guildId: String(guildId), initiativeId: params.initiativeId },
      });
    }
    throw redirect({ to: "/" });
  },
});
