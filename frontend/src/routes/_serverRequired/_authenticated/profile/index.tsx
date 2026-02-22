import { lazy, Suspense } from "react";
import { createFileRoute } from "@tanstack/react-router";
import { useAuth } from "@/hooks/useAuth";

const UserSettingsProfilePage = lazy(() =>
  import("@/pages/UserSettingsProfilePage").then((m) => ({
    default: m.UserSettingsProfilePage,
  }))
);

export const Route = createFileRoute("/_serverRequired/_authenticated/profile/")({
  component: ProfileIndexPage,
});

function ProfileIndexPage() {
  const { user, refreshUser } = useAuth();
  if (!user) return null;
  return (
    <Suspense fallback={null}>
      <UserSettingsProfilePage user={user} refreshUser={refreshUser} />
    </Suspense>
  );
}
