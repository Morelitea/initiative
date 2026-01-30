import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute("/_serverRequired/_authenticated/navigate")({
  component: lazyRouteComponent(() =>
    import("@/pages/NavigatePage").then((m) => ({ default: m.NavigatePage }))
  ),
});
