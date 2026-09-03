import { createFileRoute } from "@tanstack/react-router";
import { lazy, Suspense } from "react";

const UserSettingsPrivacyPage = lazy(() =>
  import("@/pages/user/settings/UserSettingsPrivacyPage").then((m) => ({
    default: m.UserSettingsPrivacyPage,
  }))
);

export const Route = createFileRoute("/_serverRequired/_authenticated/profile/privacy")({
  component: PrivacyPage,
});

function PrivacyPage() {
  return (
    <Suspense fallback={null}>
      <UserSettingsPrivacyPage />
    </Suspense>
  );
}
