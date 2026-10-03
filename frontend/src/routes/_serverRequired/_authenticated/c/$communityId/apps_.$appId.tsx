import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute("/_serverRequired/_authenticated/c/$communityId/apps_/$appId")(
  {
    component: lazyRouteComponent(() =>
      import("@/pages/apps/CommunityAppRoute").then((m) => ({
        default: m.CommunityAppRoute,
      }))
    ),
  }
);
