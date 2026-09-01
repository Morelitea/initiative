import { createFileRoute, redirect } from "@tanstack/react-router";

// The Export tab became the Data tab (export + import together); keep the
// old URL working for bookmarks and older notifications.
export const Route = createFileRoute("/_serverRequired/_authenticated/c/$guildId/settings/export")({
  beforeLoad: ({ params }) => {
    throw redirect({
      to: "/c/$guildId/settings/data",
      params: { guildId: params.guildId },
    });
  },
});
