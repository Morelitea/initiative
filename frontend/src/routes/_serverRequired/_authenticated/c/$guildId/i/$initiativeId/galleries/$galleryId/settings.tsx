import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$guildId/i/$initiativeId/galleries/$galleryId/settings"
)({
  component: lazyRouteComponent(() =>
    import("@/pages/initiativeTools/galleries/GallerySettingsPage").then((m) => ({
      default: m.GallerySettingsPage,
    }))
  ),
});
