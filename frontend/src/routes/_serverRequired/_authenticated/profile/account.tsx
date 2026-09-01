import { createFileRoute } from "@tanstack/react-router";
import { lazy, Suspense } from "react";

import { useAuth } from "@/hooks/useAuth";

const UserSettingsAccountPage = lazy(() =>
  import("@/pages/user/settings/UserSettingsAccountPage").then((m) => ({
    default: m.UserSettingsAccountPage,
  }))
);

export const Route = createFileRoute("/_serverRequired/_authenticated/profile/account")({
  component: AccountPage,
});

function AccountPage() {
  const { user, refreshUser } = useAuth();
  if (!user) return null;
  return (
    <Suspense fallback={null}>
      <UserSettingsAccountPage user={user} refreshUser={refreshUser} />
    </Suspense>
  );
}
