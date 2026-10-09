import { createFileRoute, redirect } from "@tanstack/react-router";

// The project's filter presets became its views.
export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/i/$initiativeId/projects/$projectId/settings/filter-presets"
)({
  beforeLoad: ({ params }) => {
    throw redirect({
      to: "/c/$communityId/i/$initiativeId/projects/$projectId/settings/views",
      params,
      replace: true,
    });
  },
});
