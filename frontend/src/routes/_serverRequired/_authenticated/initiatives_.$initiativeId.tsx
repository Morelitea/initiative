import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";
import { apiClient } from "@/api/client";

export const Route = createFileRoute("/_serverRequired/_authenticated/initiatives_/$initiativeId")({
  loader: async ({ context }) => {
    const { queryClient, guilds } = context;
    const activeGuildId = guilds?.activeGuildId ?? null;

    // Prefetch in background - don't block navigation on failure
    try {
      await queryClient.ensureQueryData({
        queryKey: ["initiatives", { guildId: activeGuildId }],
        queryFn: () => apiClient.get("/initiatives/").then((r) => r.data),
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
