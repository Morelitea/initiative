import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/i/$initiativeId/galleries/$galleryId/"
)({
  component: lazyRouteComponent(() =>
    import("@/pages/initiativeTools/galleries/GalleryDetailPage").then((m) => ({
      default: m.GalleryDetailPage,
    }))
  ),
});
