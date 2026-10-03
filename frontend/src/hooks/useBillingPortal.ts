import { useCallback } from "react";
import { useTranslation } from "react-i18next";

import { createCommunityBillingHandoff } from "@/api/generated/communities/communities";
import { useAppConfig } from "@/hooks/useAppConfig";
import { useServer } from "@/hooks/useServer";

/** Portal page to land on: the plan/card setup screen, or the existing
 *  subscription's management screen. */
export type BillingPortalPage = "manage" | "upgrade";

/**
 * Link-out to the external billing portal for one community.
 *
 * `billing` is null when the deployment has no portal configured (the
 * self-hosted default) — callers must skip every tier/upgrade/manage
 * affordance then, and `reserveTab`/`openPortal` become no-ops. It is also
 * null while the config is still loading, which `isLoading` tells apart.
 *
 * `portalUrl` is the address itself: the portal page for one community, with a
 * freshly minted handoff in its fragment. It throws when the server refuses
 * the handoff, and is null with no portal configured.
 *
 * `openPortal` opens that address in a new tab, falling back to the bare
 * portal page when the handoff fails. The tab is opened before the handoff
 * token is minted so the browser keeps attributing it to the click that
 * started it. `reserveTab` exposes that step on its own for callers with their
 * own await between the click and the hop (community creation), which would
 * otherwise land the `window.open` outside the user gesture.
 *
 * `canSell` is whether this surface may lead anyone to a purchase: a portal
 * is configured and this is not the app on a phone. The app stores refuse an
 * app that sends people to pay anywhere but the store's own checkout, so the
 * phone app shows the plan and never offers to change it — every
 * upgrade/manage affordance asks `canSell`, not `billing`, and
 * `reserveTab`/`openPortal` do nothing there.
 */
export const useBillingPortal = () => {
  const { billing, isLoading } = useAppConfig();
  const { i18n } = useTranslation();
  const lang = i18n.resolvedLanguage ?? i18n.language;
  const { isNativePlatform } = useServer();
  const canSell = billing != null && !isNativePlatform;

  const pageUrl = useCallback(
    (communityId: number, page: BillingPortalPage): string | null =>
      billing
        ? `${billing.url}/${page}?community=${communityId}&lang=${encodeURIComponent(lang)}`
        : null,
    [billing, lang]
  );

  const portalUrl = useCallback(
    async (communityId: number, page: BillingPortalPage): Promise<string | null> => {
      const base = pageUrl(communityId, page);
      if (!base) return null;
      const { handoff_token } = await createCommunityBillingHandoff(communityId);
      return `${base}#handoff=${encodeURIComponent(handoff_token)}`;
    },
    [pageUrl]
  );

  const reserveTab = useCallback((): Window | null => {
    if (!canSell) return null;
    const tab = window.open("about:blank", "_blank");
    if (tab) tab.opener = null;
    return tab;
  }, [canSell]);

  const openPortal = useCallback(
    async (communityId: number, page: BillingPortalPage, reserved?: Window | null) => {
      if (!canSell) return;
      const base = pageUrl(communityId, page);
      if (!base) return;
      const tab = reserved ?? reserveTab();
      let url = base;
      try {
        url = (await portalUrl(communityId, page)) ?? base;
      } catch {
        // Without a handoff, the bare portal page.
      }
      if (tab) tab.location.href = url;
      else window.open(url, "_blank", "noopener,noreferrer");
    },
    [canSell, pageUrl, portalUrl, reserveTab]
  );

  return { billing, canSell, isLoading, openPortal, portalUrl, reserveTab };
};
