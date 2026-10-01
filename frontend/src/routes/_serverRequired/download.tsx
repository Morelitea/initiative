import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute("/_serverRequired/download")({
  component: lazyRouteComponent(() =>
    import("@/pages/landing/DownloadPage").then((m) => ({ default: m.DownloadPage }))
  ),
});
