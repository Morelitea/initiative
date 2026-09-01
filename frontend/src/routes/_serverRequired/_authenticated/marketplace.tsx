import { createFileRoute } from "@tanstack/react-router";
import { lazy, Suspense } from "react";

import { useAuth } from "@/hooks/useAuth";

const UserMarketplacePage = lazy(() =>
  import("@/pages/marketplace/UserMarketplacePage").then((m) => ({
    default: m.UserMarketplacePage,
  }))
);

// Outside the `/c/$guildId` tree: what is sold here installs to a person, not
// to a community, and belongs to them in every community they are in.
export const Route = createFileRoute("/_serverRequired/_authenticated/marketplace")({
  component: MarketplacePage,
});

function MarketplacePage() {
  const { user } = useAuth();
  if (!user) return null;
  return (
    <Suspense fallback={null}>
      <UserMarketplacePage user={user} />
    </Suspense>
  );
}
