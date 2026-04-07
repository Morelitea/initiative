import { createFileRoute, redirect } from "@tanstack/react-router";

export const Route = createFileRoute("/_serverRequired/_authenticated/projects_/$projectId")({
  beforeLoad: ({ context, params, search }) => {
    const guildId = context.guilds?.activeGuildId;
    const typedSearch = search as { create?: string };
    if (guildId) {
      throw redirect({
        to: "/g/$guildId/projects/$projectId",
        params: { guildId: String(guildId), projectId: params.projectId },
        search: { create: typedSearch.create },
      });
    }
    throw redirect({ to: "/" });
  },
});
