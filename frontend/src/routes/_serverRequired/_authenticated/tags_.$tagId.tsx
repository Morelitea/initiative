import { createFileRoute, redirect } from "@tanstack/react-router";

export const Route = createFileRoute("/_serverRequired/_authenticated/tags_/$tagId")({
  beforeLoad: ({ context, params }) => {
    const guildId = context.guilds?.activeGuildId;
    if (guildId) {
      throw redirect({
        to: "/g/$guildId/tags/$tagId",
        params: { guildId: String(guildId), tagId: params.tagId },
      });
    }
    throw redirect({ to: "/" });
  },
});
