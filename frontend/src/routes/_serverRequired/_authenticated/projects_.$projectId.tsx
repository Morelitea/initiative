import { createFileRoute, redirect } from "@tanstack/react-router";

export const Route = createFileRoute("/_serverRequired/_authenticated/projects_/$projectId")({
  beforeLoad: ({ context, params }) => {
    const guildId = context.guilds?.activeGuildId;
    if (guildId) {
      throw redirect({
        to: "/g/$guildId/projects/$projectId",
        params: { guildId: String(guildId), projectId: params.projectId },
      });
    }
    throw redirect({ to: "/" });
  },
});
