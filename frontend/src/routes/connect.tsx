import { createFileRoute, lazyRouteComponent, redirect } from "@tanstack/react-router";

export const Route = createFileRoute("/connect")({
  // A browser is already on its server, so only the app asks for one.
  beforeLoad: ({ context }) => {
    if (context.server?.isNativePlatform === false) {
      throw redirect({ to: "/" });
    }
  },
  component: lazyRouteComponent(() =>
    import("@/pages/ConnectServerPage").then((m) => ({ default: m.ConnectServerPage }))
  ),
});
