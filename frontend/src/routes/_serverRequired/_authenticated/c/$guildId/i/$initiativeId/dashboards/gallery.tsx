import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

// Development surface for the widget harness — see WidgetGalleryPage. Not
// linked from the app; the canvas that will render widgets for real is Phase 2b.
export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$guildId/i/$initiativeId/dashboards/gallery"
)({
  component: lazyRouteComponent(() =>
    import("@/pages/initiativeTools/dashboards/WidgetGalleryPage").then((m) => ({
      default: m.WidgetGalleryPage,
    }))
  ),
});
