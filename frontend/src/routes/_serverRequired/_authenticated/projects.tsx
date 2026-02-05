import { createFileRoute, redirect } from "@tanstack/react-router";

type ProjectsSearchParams = {
  create?: string;
  initiativeId?: string;
};

export const Route = createFileRoute("/_serverRequired/_authenticated/projects")({
  validateSearch: (search: Record<string, unknown>): ProjectsSearchParams => ({
    create: typeof search.create === "string" ? search.create : undefined,
    initiativeId: typeof search.initiativeId === "string" ? search.initiativeId : undefined,
  }),
  beforeLoad: ({ context, search }) => {
    const guildId = context.guilds?.activeGuildId;
    if (guildId) {
      throw redirect({
        to: "/g/$guildId/projects",
        params: { guildId: String(guildId) },
        search,
      });
    }
    // No active guild - go to home
    throw redirect({ to: "/" });
  },
});
