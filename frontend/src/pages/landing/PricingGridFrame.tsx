/**
 * The billing portal's pricing grid, framed: the same cards, in the same
 * steps, as the portal's own pricing page, worded in the reader's language and
 * priced in their currency by the portal.
 *
 * The frame tells this page two things. Its height, so it fits without a
 * scrollbar of its own, and which plan's button was pressed, which this page
 * routes: signing up is this app's own door, buying and talking to sales go to
 * the portal, and running it yourself goes to the install guide. A message
 * counts only from the portal's origin and from this frame.
 */

import { useNavigate } from "@tanstack/react-router";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { portalPricingUrl, pricingEmbedUrl } from "@/hooks/useBillingCatalog";
import { useTheme } from "@/hooks/useTheme";
import { docsUrl } from "@/lib/links";

export const SELF_HOST_GUIDE = docsUrl("running-a-server/installation/");

/** The portal's message types; see its `EmbedPricingPage`. */
export const EMBED_HEIGHT = "initiative-billing:pricing:height";
export const EMBED_CTA = "initiative-billing:pricing:cta";

/** Until the grid says how tall it is: about one desktop row of cards. */
const INITIAL_HEIGHT = 900;
const MAX_HEIGHT = 12_000;

const originOf = (url: string): string | null => {
  try {
    return new URL(url).origin;
  } catch {
    return null;
  }
};

/** A new tab, or this one when the browser will not open one. */
const openOut = (href: string) => {
  const tab = window.open(href, "_blank", "noopener,noreferrer");
  if (!tab) window.location.assign(href);
};

export const PricingGridFrame = ({
  portalUrl,
  registrationOpen,
}: {
  portalUrl: string;
  registrationOpen: boolean;
}) => {
  const { t, i18n } = useTranslation("landing");
  const { resolvedTheme } = useTheme();
  const navigate = useNavigate();
  const frame = useRef<HTMLIFrameElement>(null);
  const [height, setHeight] = useState(INITIAL_HEIGHT);
  const lang = i18n.resolvedLanguage ?? i18n.language ?? "en";
  const theme = resolvedTheme === "dark" ? "dark" : "light";
  const portalOrigin = originOf(portalUrl);

  useEffect(() => {
    const onMessage = (event: MessageEvent) => {
      if (!portalOrigin || event.origin !== portalOrigin) return;
      if (event.source !== frame.current?.contentWindow) return;
      const data: unknown = event.data;
      if (typeof data !== "object" || data === null) return;
      const message = data as { type?: unknown; height?: unknown; kind?: unknown };
      if (message.type === EMBED_HEIGHT && typeof message.height === "number") {
        if (Number.isFinite(message.height) && message.height > 0) {
          setHeight(Math.min(Math.ceil(message.height), MAX_HEIGHT));
        }
        return;
      }
      if (message.type !== EMBED_CTA) return;
      switch (message.kind) {
        case "signup":
          void navigate({ to: registrationOpen ? "/start" : "/login" });
          break;
        case "external":
          openOut(SELF_HOST_GUIDE);
          break;
        case "checkout":
        case "contact":
          openOut(portalPricingUrl(portalUrl));
          break;
      }
    };
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, [navigate, portalOrigin, portalUrl, registrationOpen]);

  return (
    <iframe
      ref={frame}
      src={pricingEmbedUrl(portalUrl, { lang, theme })}
      title={t("pricing.tierListAria")}
      className="block w-full border-0 bg-transparent"
      style={{ height, colorScheme: theme }}
      // The grid is the portal's own page; it needs its scripts and nothing
      // more of this one.
      sandbox="allow-scripts allow-same-origin"
      referrerPolicy="no-referrer"
    />
  );
};
