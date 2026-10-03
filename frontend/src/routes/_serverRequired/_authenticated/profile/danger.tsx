import { createFileRoute, redirect } from "@tanstack/react-router";

// Deactivating and deleting the account live at the bottom of Account now.
export const Route = createFileRoute("/_serverRequired/_authenticated/profile/danger")({
  beforeLoad: () => {
    throw redirect({ to: "/profile/account", replace: true });
  },
});
