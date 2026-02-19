import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

import {
  listInitiativesApiV1InitiativesGet,
  getListInitiativesApiV1InitiativesGetQueryKey,
} from "@/api/generated/initiatives/initiatives";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/g/$guildId/initiatives_/$initiativeId"
)({
  loader: async ({ context }) => {
    const { queryClient } = context;

    // Prefetch in background - don't block navigation on failure
    try {
      await queryClient.ensureQueryData({
        queryKey: getListInitiativesApiV1InitiativesGetQueryKey(),
        queryFn: () => listInitiativesApiV1InitiativesGet(),
        staleTime: 30_000,
      });
    } catch {
      // Silently fail - component will fetch its own data
    }
  },
  component: lazyRouteComponent(() =>
    import("@/pages/InitiativeDetailPage").then((m) => ({ default: m.InitiativeDetailPage }))
  ),
});
