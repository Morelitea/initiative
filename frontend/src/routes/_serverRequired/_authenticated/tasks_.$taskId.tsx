import { createFileRoute, redirect } from "@tanstack/react-router";

export const Route = createFileRoute("/_serverRequired/_authenticated/tasks_/$taskId")({
  beforeLoad: ({ context, params }) => {
    const guildId = context.guilds?.activeGuildId;
    if (guildId) {
      throw redirect({
        to: "/g/$guildId/tasks/$taskId",
        params: { guildId: String(guildId), taskId: params.taskId },
      });
    }
    throw redirect({ to: "/" });
  },
});
