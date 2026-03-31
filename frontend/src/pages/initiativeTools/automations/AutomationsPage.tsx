import { Navigate, useSearch } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";
import { Zap } from "lucide-react";

import { useGuildPath } from "@/lib/guildUrl";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

export const AutomationsPage = () => {
  const { t } = useTranslation(["initiatives", "nav"]);
  const gp = useGuildPath();
  const search = useSearch({ strict: false }) as { initiativeId?: string };

  if (!__ENABLE_AUTOMATIONS__) {
    return <Navigate to={gp("/initiatives")} replace />;
  }

  return (
    <div className="space-y-6">
      <div className="space-y-1">
        <h1 className="text-3xl font-semibold tracking-tight">{t("nav:automations")}</h1>
        {search.initiativeId && (
          <p className="text-muted-foreground text-sm">{t("initiatives:automationsScoped")}</p>
        )}
      </div>

      <Card>
        <CardHeader>
          <div className="flex items-center gap-3">
            <div className="bg-primary/10 flex h-10 w-10 items-center justify-center rounded-lg">
              <Zap className="text-primary h-5 w-5" />
            </div>
            <div>
              <CardTitle>{t("initiatives:automationsComingSoon")}</CardTitle>
              <CardDescription>{t("initiatives:automationsComingSoonDescription")}</CardDescription>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          <p className="text-muted-foreground text-sm">{t("initiatives:automationsPlaceholder")}</p>
        </CardContent>
      </Card>
    </div>
  );
};
