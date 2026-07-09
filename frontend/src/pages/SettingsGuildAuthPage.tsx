import { useTranslation } from "react-i18next";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

/**
 * Placeholder for guild-scoped sign-in configuration (visible only when the
 * platform's login posture is per-guild). Guild provider CRUD and membership
 * rules land here in a later phase; until then this page states what's coming.
 */
export const SettingsGuildAuthPage = () => {
  const { t } = useTranslation("settings");

  return (
    <Card className="shadow-sm">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          {t("guildAuth.title")}
          <Badge variant="secondary">{t("guildAuth.comingSoon")}</Badge>
        </CardTitle>
        <CardDescription>{t("guildAuth.description")}</CardDescription>
      </CardHeader>
      <CardContent>
        <p className="text-muted-foreground text-sm">{t("guildAuth.body")}</p>
      </CardContent>
    </Card>
  );
};
