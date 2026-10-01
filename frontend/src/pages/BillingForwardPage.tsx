import { useParams, useSearch } from "@tanstack/react-router";
import { CreditCard, Globe, Loader2, ShieldAlert } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { StatusMessage } from "@/components/StatusMessage";
import { type BillingPortalPage, useBillingPortal } from "@/hooks/useBillingPortal";
import { useServer } from "@/hooks/useServer";
import { getErrorMessage } from "@/lib/errorMessage";

/**
 * `/c/$guildId/billing?page=…`: mints a portal handoff for the community and
 * replaces this tab with the portal, so Back does not land here again.
 *
 * The app on a phone shows where to go instead of going there: plans are
 * bought in a browser, not in the app.
 */
export const BillingForwardPage = () => {
  const { t } = useTranslation("guilds");
  const { guildId } = useParams({ strict: false }) as { guildId?: string };
  const { page } = useSearch({ strict: false }) as { page?: BillingPortalPage };
  const { isNativePlatform } = useServer();
  const { billing, isLoading, portalUrl } = useBillingPortal();
  const [error, setError] = useState<string | null>(null);
  // Once per visit, StrictMode's second effect included: each request mints a token.
  const started = useRef(false);

  const id = Number(guildId);
  const target: BillingPortalPage = page === "upgrade" ? "upgrade" : "manage";

  useEffect(() => {
    if (started.current || isNativePlatform || isLoading || !billing) return;
    started.current = true;
    if (!Number.isInteger(id) || id <= 0) {
      setError(t("billingForward.error"));
      return;
    }
    portalUrl(id, target)
      .then((url) => {
        if (url) window.location.replace(url);
      })
      .catch((err: unknown) => setError(getErrorMessage(err, "guilds:billingForward.error")));
  }, [billing, id, isLoading, isNativePlatform, portalUrl, t, target]);

  const message = (icon: React.ReactNode, title: string, description: string) => (
    <div className="flex min-h-screen items-center justify-center">
      <StatusMessage
        icon={icon}
        title={title}
        description={description}
        backTo="/"
        backLabel={t("notMember.backToHome")}
      />
    </div>
  );

  if (isNativePlatform) {
    return message(
      <Globe />,
      t("billingForward.nativeTitle"),
      t("billingForward.nativeDescription")
    );
  }
  if (!isLoading && !billing) {
    return message(
      <CreditCard />,
      t("billingForward.notConfiguredTitle"),
      t("billingForward.notConfiguredDescription")
    );
  }
  if (error) {
    return message(<ShieldAlert />, t("billingForward.errorTitle"), error);
  }
  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-3 px-6 text-center">
      <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      <p className="text-muted-foreground text-sm">{t("billingForward.opening")}</p>
    </div>
  );
};
