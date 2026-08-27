import { useCallback } from "react";
import { useTranslation } from "react-i18next";

import { createGuildBillingHandoffApiV1GuildsGuildIdBillingHandoffPost } from "@/api/generated/guilds/guilds";
import { useAppConfig } from "@/hooks/useAppConfig";

/** Portal page to land on: the plan/card setup screen, or the existing
 *  subscription's management screen. */
export type BillingPortalPage = "manage" | "upgrade";

/**
 * Link-out to the external billing portal for one guild.
 *
 * `billing` is null when the deployment has no portal configured (the
 * self-hosted default) — callers must skip every tier/upgrade/manage
 * affordance then, and `reserveTab`/`openPortal` become no-ops.
 *
 * The tab is opened before the handoff token is minted so the browser keeps
 * attributing it to the click that started it. `reserveTab` exposes that step
 * on its own for callers with their own await between the click and the hop
 * (guild creation), which would otherwise land the `window.open` outside the
 * user gesture.
 */
export const useBillingPortal = () => {
  const { billing } = useAppConfig();
  const { i18n } = useTranslation();
  const lang = i18n.resolvedLanguage ?? i18n.language;

  const reserveTab = useCallback((): Window | null => {
    if (!billing) return null;
    const tab = window.open("about:blank", "_blank");
    if (tab) tab.opener = null;
    return tab;
  }, [billing]);

  const openPortal = useCallback(
    async (guildId: number, page: BillingPortalPage, reserved?: Window | null) => {
      if (!billing) return;
      const base = `${billing.url}/${page}?guild=${guildId}&lang=${encodeURIComponent(lang)}`;
      const tab = reserved ?? reserveTab();
      try {
        const { handoff_token } =
          await createGuildBillingHandoffApiV1GuildsGuildIdBillingHandoffPost(guildId);
        const url = `${base}#handoff=${encodeURIComponent(handoff_token)}`;
        if (tab) tab.location.href = url;
        else window.open(url, "_blank", "noopener,noreferrer");
      } catch {
        if (tab) tab.location.href = base;
        else window.open(base, "_blank", "noopener,noreferrer");
      }
    },
    [billing, lang, reserveTab]
  );

  return { billing, openPortal, reserveTab };
};
