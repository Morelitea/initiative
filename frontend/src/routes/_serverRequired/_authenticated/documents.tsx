import { createFileRoute, redirect } from "@tanstack/react-router";

type DocumentsSearchParams = {
  create?: string;
  initiativeId?: string;
  page?: number;
};

export const Route = createFileRoute("/_serverRequired/_authenticated/documents")({
  validateSearch: (search: Record<string, unknown>): DocumentsSearchParams => ({
    create: typeof search.create === "string" ? search.create : undefined,
    initiativeId: typeof search.initiativeId === "string" ? search.initiativeId : undefined,
    page:
      typeof search.page === "number" && search.page >= 1
        ? search.page
        : typeof search.page === "string" && Number(search.page) >= 1
          ? Number(search.page)
          : undefined,
  }),
  beforeLoad: ({ context, search }) => {
    const guildId = context.guilds?.activeGuildId;
    if (guildId) {
      throw redirect({
        to: "/g/$guildId/documents",
        params: { guildId: String(guildId) },
        search,
      });
    }
    throw redirect({ to: "/" });
  },
});
