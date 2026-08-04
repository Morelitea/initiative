import { useTranslation } from "react-i18next";

import {
  AIConnectionManager,
  type ConnectionMutations,
} from "@/components/settings/AIConnectionManager";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useActiveGuildId } from "@/hooks/useActiveGuildId";
import {
  useCreateGuildConnection,
  useDeleteGuildConnection,
  useFetchGuildConnectionModels,
  useGuildConnections,
  useMemberAI,
  useTestGuildConnection,
  useUpdateGuildConnection,
} from "@/hooks/useAISettings";
import { useGuilds } from "@/hooks/useGuilds";
import { getProvidersForScope } from "@/lib/ai-providers";

/**
 * Guild-ADMIN AI surface: manage the guild's own AI connections (destinations)
 * when the platform is in `guild` mode. A member's personal key lives under
 * their profile settings ("My AI keys"), not here.
 */
export const SettingsGuildAIPage = () => {
  const { t } = useTranslation("settings");
  const { activeGuild, activeGuildReadOnly } = useGuilds();
  const guildId = useActiveGuildId();
  const isGuildAdmin = activeGuild?.role === "admin" && !activeGuildReadOnly;

  // The member view is the readable-by-anyone source of the global AI mode.
  const modeQuery = useMemberAI(guildId, { enabled: isGuildAdmin });
  const mode = modeQuery.data?.mode;
  const canManageConnections = mode === "guild";

  const connectionsQuery = useGuildConnections({
    enabled: Boolean(isGuildAdmin) && canManageConnections,
  });

  const mutations: ConnectionMutations = {
    create: useCreateGuildConnection(),
    update: useUpdateGuildConnection(),
    remove: useDeleteGuildConnection(),
    test: useTestGuildConnection(),
    fetchModels: useFetchGuildConnectionModels(),
  };

  if (!isGuildAdmin) {
    return <p className="text-muted-foreground text-sm">{t("guildAI.adminOnly")}</p>;
  }

  if (modeQuery.isLoading) {
    return <p className="text-muted-foreground text-sm">{t("ai.loading")}</p>;
  }

  if (modeQuery.isError || !modeQuery.data) {
    return <p className="text-destructive text-sm">{t("ai.loadError")}</p>;
  }

  if (mode === "disabled") {
    return (
      <Card className="shadow-sm">
        <CardHeader>
          <CardTitle>{t("guildAI.title")}</CardTitle>
          <CardDescription>{t("guildAI.disabledDescription")}</CardDescription>
        </CardHeader>
      </Card>
    );
  }

  if (mode === "platform") {
    return (
      <Card className="shadow-sm">
        <CardHeader>
          <CardTitle>{t("guildAI.title")}</CardTitle>
          <CardDescription>{t("guildAI.managedByPlatform")}</CardDescription>
        </CardHeader>
      </Card>
    );
  }

  return (
    <Card className="shadow-sm">
      <CardHeader>
        <CardTitle>{t("guildAI.connectionsTitle")}</CardTitle>
        <CardDescription>{t("guildAI.connectionsDescription")}</CardDescription>
      </CardHeader>
      <CardContent>
        <AIConnectionManager
          scope="guild"
          connections={connectionsQuery.data ?? []}
          isLoading={connectionsQuery.isLoading}
          isError={connectionsQuery.isError}
          providers={getProvidersForScope("guild")}
          mutations={mutations}
        />
      </CardContent>
    </Card>
  );
};
