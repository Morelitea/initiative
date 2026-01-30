import { createFileRoute, redirect } from "@tanstack/react-router";

export const Route = createFileRoute("/_serverRequired/_authenticated/settings")({
  beforeLoad: ({ location }) => {
    // Only redirect if we're at exactly /settings, not a child route like /settings/admin
    if (location.pathname === "/settings" || location.pathname === "/settings/") {
      throw redirect({ to: "/settings/guild" });
    }
  },
});
