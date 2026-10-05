import { useTranslation } from "react-i18next";

import {
  AIConnectionManager,
  type ConnectionMutations,
} from "@/components/settings/AIConnectionManager";
import { FormSkeleton, SkeletonRegion } from "@/components/skeletons/PageSkeletons";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import {
  useCommunityConnections,
  useCreateCommunityConnection,
  useDeleteCommunityConnection,
  useFetchCommunityConnectionModels,
  useMemberAI,
  useTestCommunityConnection,
  useUpdateCommunityConnection,
} from "@/hooks/useAISettings";
import { useCommunities } from "@/hooks/useCommunities";
import { getProvidersForScope } from "@/lib/ai-providers";

/**
 * Community-ADMIN AI surface: manage the community's own AI connections (destinations)
 * when the platform is in `community` mode. A member's personal key lives under
 * their profile settings ("My AI keys"), not here.
 */
export const SettingsCommunityAIPage = () => {
  const { t } = useTranslation("settings");
  const { activeCommunity, activeCommunityReadOnly } = useCommunities();
  const communityId = useActiveCommunityId();
  // The seat, not admin-or-above: connecting a provider says what leaves
  // the community. The tab is gated the same way; this is the direct-URL half.
  const holdsTheSeat = Boolean(activeCommunity?.can.seat) && !activeCommunityReadOnly;

  // The member view is the readable-by-anyone source of the global AI mode.
  const modeQuery = useMemberAI(communityId, { enabled: holdsTheSeat });
  const mode = modeQuery.data?.mode;
  const canManageConnections = mode === "community";

  const connectionsQuery = useCommunityConnections({
    enabled: Boolean(holdsTheSeat) && canManageConnections,
  });

  const mutations: ConnectionMutations = {
    create: useCreateCommunityConnection(),
    update: useUpdateCommunityConnection(),
    remove: useDeleteCommunityConnection(),
    test: useTestCommunityConnection(),
    fetchModels: useFetchCommunityConnectionModels(),
  };

  if (!holdsTheSeat) {
    return <p className="text-muted-foreground text-sm">{t("communityAI.adminOnly")}</p>;
  }

  if (modeQuery.isLoading) {
    return (
      <SkeletonRegion label={t("ai.loading")}>
        <FormSkeleton fields={2} />
      </SkeletonRegion>
    );
  }

  if (modeQuery.isError || !modeQuery.data) {
    return <p className="text-destructive text-sm">{t("ai.loadError")}</p>;
  }

  if (mode === "disabled") {
    return (
      <Card>
        <CardHeader>
          <CardTitle>{t("communityAI.title")}</CardTitle>
          <CardDescription>{t("communityAI.disabledDescription")}</CardDescription>
        </CardHeader>
      </Card>
    );
  }

  if (mode === "platform") {
    return (
      <Card>
        <CardHeader>
          <CardTitle>{t("communityAI.title")}</CardTitle>
          <CardDescription>{t("communityAI.managedByPlatform")}</CardDescription>
        </CardHeader>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("communityAI.connectionsTitle")}</CardTitle>
        <CardDescription>{t("communityAI.connectionsDescription")}</CardDescription>
      </CardHeader>
      <CardContent>
        <AIConnectionManager
          scope="community"
          connections={connectionsQuery.data ?? []}
          isLoading={connectionsQuery.isLoading}
          isError={connectionsQuery.isError}
          providers={getProvidersForScope("community")}
          mutations={mutations}
        />
      </CardContent>
    </Card>
  );
};
