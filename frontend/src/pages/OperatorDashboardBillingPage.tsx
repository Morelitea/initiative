/**
 * The operator dashboard's Billing tab: the way into the billing service's
 * insights page — how the business is doing, across every community.
 *
 * Unlike the per-community billing buttons on the Communities tab, this opens
 * no community and takes no access grant: the page shows the payment
 * processor's account-wide figures and counts that name no community, so the
 * handoff names only the person opening it (`billing.insights`).
 */

import { BarChart3, ExternalLink } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { createBillingInsightsHandoff } from "@/api/generated/settings/settings";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useAppConfig } from "@/hooks/useAppConfig";
import { useAuth } from "@/hooks/useAuth";
import { getErrorMessage } from "@/lib/errorMessage";
import { toast } from "@/lib/mascotToast";
import { Capability, hasCapability } from "@/lib/permissions";

export const OperatorDashboardBillingPage = () => {
  const { t, i18n } = useTranslation("settings");
  const { user } = useAuth();
  const { billing } = useAppConfig();
  const [opening, setOpening] = useState(false);

  if (!hasCapability(user, Capability.billingInsights)) {
    return <p className="text-muted-foreground text-sm">{t("billingInsights.platformOnly")}</p>;
  }

  const open = async () => {
    if (!billing) return;
    setOpening(true);
    // Opened inside the click, before the request, so it is not a popup.
    const tab = window.open("about:blank", "_blank");
    if (tab) tab.opener = null;
    try {
      const { handoff_token } = await createBillingInsightsHandoff();
      const lang = i18n.resolvedLanguage ?? i18n.language;
      // The token rides in the fragment, which never leaves the browser.
      const url = `${billing.url.replace(/\/+$/, "")}/insights?lang=${encodeURIComponent(
        lang
      )}#insights_handoff=${encodeURIComponent(handoff_token)}`;
      if (tab) tab.location.href = url;
      else window.open(url, "_blank", "noopener,noreferrer");
    } catch (err) {
      tab?.close();
      toast.error(getErrorMessage(err, "settings:billingInsights.openError"));
    } finally {
      setOpening(false);
    }
  };

  return (
    <Card className="shadow-sm">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <BarChart3 className="h-5 w-5" aria-hidden />
          {t("billingInsights.title")}
        </CardTitle>
        <CardDescription>{t("billingInsights.description")}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <ul className="list-disc space-y-1 pl-5 text-muted-foreground text-sm">
          <li>{t("billingInsights.fromPaddle")}</li>
          <li>{t("billingInsights.fromBilling")}</li>
          <li>{t("billingInsights.noCommunity")}</li>
        </ul>
        {billing?.insights ? (
          <Button onClick={() => void open()} disabled={opening}>
            <ExternalLink className="h-4 w-4" aria-hidden />
            {opening ? t("billingInsights.opening") : t("billingInsights.open")}
          </Button>
        ) : (
          <p className="text-muted-foreground text-sm">{t("billingInsights.notConfigured")}</p>
        )}
      </CardContent>
    </Card>
  );
};
