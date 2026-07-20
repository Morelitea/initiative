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
import { useGuildLoginProviders, useLoginProviders } from "@/hooks/useGuildAuthPolicy";

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
  const [challenge, setChallenge] = useState<StepUpEventDetail | null>(null);
  const open = challenge !== null;

  useEffect(() => {
    if (Capacitor.isNativePlatform()) {
      return;
    }
    const onStepUp = (event: Event) => {
      const detail = (event as CustomEvent<StepUpEventDetail>).detail;
      if (detail?.providerSlug) {
        // First challenge wins; concurrent 401s from one page all name the
        // same provider.
        setChallenge((current) => current ?? detail);
      }
    };
    window.addEventListener(AUTH_STEP_UP_EVENT, onStepUp);
    return () => window.removeEventListener(AUTH_STEP_UP_EVENT, onStepUp);
  }, []);

  // A guild-scoped provider resolves its login URL through the guild's own
  // listing; the operator-global listing serves platform-posture servers.
  const guildId = challenge?.guildId ?? 0;
  const guildProvidersQuery = useGuildLoginProviders(guildId, { enabled: open && guildId > 0 });
  const platformProvidersQuery = useLoginProviders({ enabled: open && guildId <= 0 });
  const providerSlug = challenge?.providerSlug ?? null;
  const listing = guildId > 0 ? guildProvidersQuery.data : platformProvidersQuery.data;
  const provider = listing?.providers.find((entry) => entry.slug === providerSlug);
  const providerName = provider?.display_name ?? providerSlug ?? "";

  const beginStepUp = () => {
    if (!providerSlug) {
      return;
    }
    const fallbackUrl =
      guildId > 0
        ? `/api/v1/auth/g/${guildId}/${encodeURIComponent(providerSlug)}/login`
        : `/api/v1/auth/${encodeURIComponent(providerSlug)}/login`;
    const loginUrl = provider?.login_url ?? fallbackUrl;
    window.location.href = `${loginUrl}?next=${encodeURIComponent(currentSpaPath())}`;
  };

  return (
    <Dialog open={open} onOpenChange={(next) => !next && setChallenge(null)}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("stepUp.title")}</DialogTitle>
          <DialogDescription>{t("stepUp.description", { providerName })}</DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button variant="outline" onClick={() => setChallenge(null)}>
            {t("stepUp.dismiss")}
          </Button>
          <Button onClick={beginStepUp}>{t("stepUp.continue", { providerName })}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};
