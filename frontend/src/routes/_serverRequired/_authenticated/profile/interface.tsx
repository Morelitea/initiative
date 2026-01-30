import { createFileRoute } from "@tanstack/react-router";
import { useAuth } from "@/hooks/useAuth";
import { UserSettingsInterfacePage } from "@/pages/UserSettingsInterfacePage";

export const Route = createFileRoute("/_serverRequired/_authenticated/profile/interface")({
  component: InterfacePage,
});

function InterfacePage() {
  const { user, refreshUser } = useAuth();
  if (!user) return null;
  return <UserSettingsInterfacePage user={user} refreshUser={refreshUser} />;
}
