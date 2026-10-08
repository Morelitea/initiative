import { createFileRoute } from "@tanstack/react-router";
import { lazy, Suspense } from "react";

import { useAuth } from "@/hooks/useAuth";

const UserSettingsInterfacePage = lazy(() =>
  import("@/pages/user/settings/UserSettingsInterfacePage").then((m) => ({
    default: m.UserSettingsInterfacePage,
  }))
);

export const Route = createFileRoute("/_serverRequired/_authenticated/profile/interface")({
  component: InterfacePage,
});

function InterfacePage() {
  const { user, acceptUser } = useAuth();
  if (!user) return null;
  return (
    <Suspense fallback={null}>
      <UserSettingsInterfacePage user={user} acceptUser={acceptUser} />
    </Suspense>
  );
}
