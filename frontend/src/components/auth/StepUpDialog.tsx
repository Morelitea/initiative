import { Capacitor } from "@capacitor/core";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { AUTH_STEP_UP_EVENT, type StepUpEventDetail } from "@/api/client";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useLoginProviders } from "@/hooks/useGuildAuthPolicy";

/** The path the sign-in should return to: where the challenge happened. */
const currentSpaPath = (): string => `${window.location.pathname}${window.location.search}`;

/**
 * Global handler for guild sign-in requirements. When any request is refused
 * with `GUILD_AUTH_STEP_UP_REQUIRED` (dispatched by the API client as a
 * window event carrying the required provider's slug), this dialog offers
 * that provider's sign-in and returns the browser to the interrupted page
 * afterwards via the login route's `next` parameter.
 *
 * Web only: the native login flow does not yet mint sessions that can
 * satisfy a guild requirement, so the event is ignored there rather than
 * sending the user through a sign-in that cannot help.
 */
export const StepUpDialog = () => {
  const { t } = useTranslation("auth");
  const [providerSlug, setProviderSlug] = useState<string | null>(null);
  const open = providerSlug !== null;

  useEffect(() => {
    if (Capacitor.isNativePlatform()) {
      return;
    }
    const onStepUp = (event: Event) => {
      const detail = (event as CustomEvent<StepUpEventDetail>).detail;
      if (detail?.providerSlug) {
        // First challenge wins; concurrent 401s from one page all name the
        // same provider.
        setProviderSlug((current) => current ?? detail.providerSlug);
      }
    };
    window.addEventListener(AUTH_STEP_UP_EVENT, onStepUp);
    return () => window.removeEventListener(AUTH_STEP_UP_EVENT, onStepUp);
  }, []);

  const providersQuery = useLoginProviders({ enabled: open });
  const provider = providersQuery.data?.providers.find((entry) => entry.slug === providerSlug);
  const providerName = provider?.display_name ?? providerSlug ?? "";

  const beginStepUp = () => {
    if (!providerSlug) {
      return;
    }
    const loginUrl =
      provider?.login_url ?? `/api/v1/auth/${encodeURIComponent(providerSlug)}/login`;
    window.location.href = `${loginUrl}?next=${encodeURIComponent(currentSpaPath())}`;
  };

  return (
    <Dialog open={open} onOpenChange={(next) => !next && setProviderSlug(null)}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("stepUp.title")}</DialogTitle>
          <DialogDescription>{t("stepUp.description", { providerName })}</DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button variant="outline" onClick={() => setProviderSlug(null)}>
            {t("stepUp.dismiss")}
          </Button>
          <Button onClick={beginStepUp}>{t("stepUp.continue", { providerName })}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};
