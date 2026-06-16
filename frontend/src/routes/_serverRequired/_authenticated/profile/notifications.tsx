import { createFileRoute } from "@tanstack/react-router";
import { lazy, Suspense } from "react";

import { useAuth } from "@/hooks/useAuth";

const UserSettingsNotificationsPage = lazy(() =>
  import("@/pages/user/settings/UserSettingsNotificationsPage").then((m) => ({
    default: m.UserSettingsNotificationsPage,
  }))
);

export const Route = createFileRoute("/_serverRequired/_authenticated/profile/notifications")({
  component: NotificationsPage,
});

function NotificationsPage() {
  const { user, refreshUser } = useAuth();
  if (!user) return null;
  return (
    <Suspense fallback={null}>
      <UserSettingsNotificationsPage user={user} refreshUser={refreshUser} />
    </Suspense>
  );
}
