import { createFileRoute } from "@tanstack/react-router";
import { lazy, Suspense } from "react";

const NotificationsInboxPage = lazy(() =>
  import("@/pages/user/NotificationsInboxPage").then((m) => ({
    default: m.NotificationsInboxPage,
  }))
);

export const Route = createFileRoute("/_serverRequired/_authenticated/notifications")({
  component: NotificationsRoute,
});

function NotificationsRoute() {
  return (
    <Suspense fallback={null}>
      <NotificationsInboxPage />
    </Suspense>
  );
}
