import { createFileRoute } from "@tanstack/react-router";
import { lazy, Suspense } from "react";

import { useAuth } from "@/hooks/useAuth";

const UserSettingsDecorationsPage = lazy(() =>
  import("@/pages/user/settings/UserSettingsDecorationsPage").then((m) => ({
    default: m.UserSettingsDecorationsPage,
  }))
);

export const Route = createFileRoute("/_serverRequired/_authenticated/profile/decorations")({
  component: DecorationsPage,
});

function DecorationsPage() {
  const { user, refreshUser } = useAuth();
  if (!user) return null;
  return (
    <Suspense fallback={null}>
      <UserSettingsDecorationsPage user={user} refreshUser={refreshUser} />
    </Suspense>
  );
}
