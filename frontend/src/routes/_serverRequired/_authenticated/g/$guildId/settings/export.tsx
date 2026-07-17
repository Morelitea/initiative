import { createFileRoute, redirect } from "@tanstack/react-router";

// The Export tab became the Data tab (export + import together); keep the
// old URL working for bookmarks and older notifications.
export const Route = createFileRoute("/_serverRequired/_authenticated/g/$guildId/settings/export")({
  beforeLoad: ({ params }) => {
    throw redirect({
      to: "/g/$guildId/settings/data",
      params: { guildId: params.guildId },
    });
  },
});
