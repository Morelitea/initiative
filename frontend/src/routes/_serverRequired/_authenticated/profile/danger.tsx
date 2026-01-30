import { createFileRoute } from "@tanstack/react-router";
import { useAuth } from "@/hooks/useAuth";
import { UserSettingsDangerZonePage } from "@/pages/UserSettingsDangerZonePage";

export const Route = createFileRoute("/_serverRequired/_authenticated/profile/danger")({
  component: DangerZonePage,
});

function DangerZonePage() {
  const { user, logout } = useAuth();
  if (!user) return null;
  return <UserSettingsDangerZonePage user={user} logout={logout} />;
}
