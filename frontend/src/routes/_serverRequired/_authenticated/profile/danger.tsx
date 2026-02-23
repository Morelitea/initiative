import { lazy, Suspense } from "react";
import { createFileRoute } from "@tanstack/react-router";
import { useAuth } from "@/hooks/useAuth";

const UserSettingsDangerZonePage = lazy(() =>
  import("@/pages/UserSettingsDangerZonePage").then((m) => ({
    default: m.UserSettingsDangerZonePage,
  }))
);

export const Route = createFileRoute("/_serverRequired/_authenticated/profile/danger")({
  component: DangerZonePage,
});

function DangerZonePage() {
  const { user, logout } = useAuth();
  if (!user) return null;
  return (
    <Suspense fallback={null}>
      <UserSettingsDangerZonePage user={user} logout={logout} />
    </Suspense>
  );
}
