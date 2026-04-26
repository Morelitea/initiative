import { useTranslation } from "react-i18next";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { RetentionSettingCard } from "@/components/trash/RetentionSettingCard";
import { TrashTable } from "@/components/trash/TrashTable";
import { useGuilds } from "@/hooks/useGuilds";

export const SettingsGuildTrashPage = () => {
  const { t } = useTranslation("trash");
  const { activeGuild } = useGuilds();
  const isGuildAdmin = activeGuild?.role === "admin";

  return (
    <div className="space-y-6">
      {isGuildAdmin ? <RetentionSettingCard /> : null}
      <Card>
        <CardHeader>
          <CardTitle>{t("title")}</CardTitle>
          <CardDescription>{t("description")}</CardDescription>
        </CardHeader>
        <CardContent>
          <TrashTable scope={isGuildAdmin ? "guild" : "mine"} showPurgeAction={isGuildAdmin} />
        </CardContent>
      </Card>
    </div>
  );
};

export default SettingsGuildTrashPage;
