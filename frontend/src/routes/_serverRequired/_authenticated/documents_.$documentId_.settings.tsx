import { createFileRoute, redirect } from "@tanstack/react-router";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/documents_/$documentId_/settings"
)({
  beforeLoad: ({ context, params }) => {
    const guildId = context.guilds?.activeGuildId;
    if (guildId) {
      throw redirect({
        to: "/g/$guildId/documents/$documentId/settings",
        params: { guildId: String(guildId), documentId: params.documentId },
      });
    }
    throw redirect({ to: "/" });
  },
});
