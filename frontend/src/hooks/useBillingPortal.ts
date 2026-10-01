import { useCallback } from "react";
import { useTranslation } from "react-i18next";

import { createGuildBillingHandoffApiV1CommunitiesGuildIdBillingHandoffPost } from "@/api/generated/communities/communities";
import { useAppConfig } from "@/hooks/useAppConfig";

/** Portal page to land on: the plan/card setup screen, or the existing
 *  subscription's management screen. */
export type BillingPortalPage = "manage" | "upgrade";

/**
 * Link-out to the external billing portal for one guild.
 *
 * `billing` is null when the deployment has no portal configured (the
 * self-hosted default) — callers must skip every tier/upgrade/manage
 * affordance then, and `reserveTab`/`openPortal` become no-ops. It is also
 * null while the config is still loading, which `isLoading` tells apart.
 *
 * `portalUrl` is the address itself: the portal page for one guild, with a
 * freshly minted handoff in its fragment. It throws when the server refuses
 * the handoff, and is null with no portal configured.
 *
 * `openPortal` opens that address in a new tab, falling back to the bare
 * portal page when the handoff fails. The tab is opened before the handoff
 * token is minted so the browser keeps attributing it to the click that
 * started it. `reserveTab` exposes that step on its own for callers with their
 * own await between the click and the hop (guild creation), which would
 * otherwise land the `window.open` outside the user gesture.
 */
export const useBillingPortal = () => {
  const { billing, isLoading } = useAppConfig();
  const { i18n } = useTranslation();
  const lang = i18n.resolvedLanguage ?? i18n.language;

  const pageUrl = useCallback(
    (guildId: number, page: BillingPortalPage): string | null =>
      billing ? `${billing.url}/${page}?guild=${guildId}&lang=${encodeURIComponent(lang)}` : null,
    [billing, lang]
  );

  const portalUrl = useCallback(
    async (guildId: number, page: BillingPortalPage): Promise<string | null> => {
      const base = pageUrl(guildId, page);
      if (!base) return null;
      const { handoff_token } =
        await createGuildBillingHandoffApiV1CommunitiesGuildIdBillingHandoffPost(guildId);
      return `${base}#handoff=${encodeURIComponent(handoff_token)}`;
    },
    [pageUrl]
  );

  const reserveTab = useCallback((): Window | null => {
    if (!billing) return null;
    const tab = window.open("about:blank", "_blank");
    if (tab) tab.opener = null;
    return tab;
  }, [billing]);

  const openPortal = useCallback(
    async (guildId: number, page: BillingPortalPage, reserved?: Window | null) => {
      const base = pageUrl(guildId, page);
      if (!base) return;
      const tab = reserved ?? reserveTab();
      let url = base;
      try {
        url = (await portalUrl(guildId, page)) ?? base;
      } catch {
        // Without a handoff, the bare portal page.
      }
      if (tab) tab.location.href = url;
      else window.open(url, "_blank", "noopener,noreferrer");
    },
    [pageUrl, portalUrl, reserveTab]
  );

  return { billing, isLoading, openPortal, portalUrl, reserveTab };
};
