import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

import {
  getListInitiativesApiV1GGuildIdInitiativesGetQueryKey,
  listInitiativesApiV1GGuildIdInitiativesGet,
} from "@/api/generated/initiatives/initiatives";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/g/$guildId/initiatives_/$initiativeId"
)({
  loader: async ({ context, params }) => {
    const { queryClient } = context;
    const guildId = Number(params.guildId);

    // Prefetch in background - don't block navigation on failure
    try {
      await queryClient.ensureQueryData({
        queryKey: getListInitiativesApiV1GGuildIdInitiativesGetQueryKey(guildId),
        queryFn: () => listInitiativesApiV1GGuildIdInitiativesGet(guildId),
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
