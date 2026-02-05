import { createFileRoute, redirect } from "@tanstack/react-router";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/projects_/$projectId_/settings"
)({
  beforeLoad: ({ context, params }) => {
    const guildId = context.guilds?.activeGuildId;
    if (guildId) {
      throw redirect({
        to: "/g/$guildId/projects/$projectId/settings",
        params: { guildId: String(guildId), projectId: params.projectId },
      });
    }
    throw redirect({ to: "/" });
  },
});
