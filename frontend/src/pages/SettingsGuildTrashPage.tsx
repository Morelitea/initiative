import { useTranslation } from "react-i18next";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { TrashTable } from "@/components/trash/TrashTable";
import { useGuilds } from "@/hooks/useGuilds";

export const SettingsGuildTrashPage = () => {
  const { t } = useTranslation("trash");
  const { activeGuild } = useGuilds();
  const isGuildAdmin = activeGuild?.role === "admin";

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("title")}</CardTitle>
        <CardDescription>{t("description")}</CardDescription>
      </CardHeader>
      <CardContent>
        {/* Guild settings is admin-gated by the layout, so guild scope is
            available here. The "Delete now" purge action is also admin-only,
            matched by showPurgeAction. */}
        <TrashTable scope={isGuildAdmin ? "guild" : "mine"} showPurgeAction={isGuildAdmin} />
      </CardContent>
    </Card>
  );
};

export default SettingsGuildTrashPage;
