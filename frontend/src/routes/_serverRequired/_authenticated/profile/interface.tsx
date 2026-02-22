import { lazy, Suspense } from "react";
import { createFileRoute } from "@tanstack/react-router";
import { useAuth } from "@/hooks/useAuth";

const UserSettingsInterfacePage = lazy(() =>
  import("@/pages/UserSettingsInterfacePage").then((m) => ({
    default: m.UserSettingsInterfacePage,
  }))
);

export const Route = createFileRoute("/_serverRequired/_authenticated/profile/interface")({
  component: InterfacePage,
});

function InterfacePage() {
  const { user, refreshUser } = useAuth();
  if (!user) return null;
  return (
    <Suspense fallback={null}>
      <UserSettingsInterfacePage user={user} refreshUser={refreshUser} />
    </Suspense>
  );
}
