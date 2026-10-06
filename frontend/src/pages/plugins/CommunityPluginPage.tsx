/**
 * A plug-in's own surface, in an iframe.
 *
 * The security shape, which mirrors what the mint endpoint already enforces:
 *
 * 1. The server decides whether a surface may be opened — the install must be
 *    enabled, its registration live, and the seat's placement and roles must
 *    admit the caller. A refusal never reaches the plug-in.
 * 2. The token is delivered by `postMessage` to the iframe's own origin, never
 *    in the URL, so it stays out of history, referrers and proxy logs.
 * 3. Inbound messages are ignored unless `event.origin` is one the registration
 *    listed and `event.source` is the frame this page mounted.
 * 4. The token is one-shot, so a reloading embed asks again and gets a fresh
 *    one rather than being stuck until the page is reloaded.
 * 5. The frame is granted the browser features the surface's manifest declared,
 *    and no others.
 *
 * The handoff also carries `sells`: whether this host may lead anyone to a
 * purchase here (a billing portal is configured, and this device may sell —
 * see `@/lib/storeSelling`). An embedded plug-in hides its own purchase copy when
 * it is false.
 */

import { Loader2 } from "lucide-react";
import { type ReactNode, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import type { CommunityPluginHandoff } from "@/api/generated/initiativeAPI.schemas";
import {
  createCommunityPluginHandoff,
  createInitiativePluginHandoff,
} from "@/api/generated/plugins/plugins";
import { ReportButton } from "@/components/moderation/ReportButton";
import { PluginProviderNotice, pluginNoticeKey } from "@/components/plugins/PluginProviderNotice";
import {
  EditorSkeleton,
  SkeletonPillRow,
  SkeletonRegion,
} from "@/components/skeletons/PageSkeletons";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { useAuth } from "@/hooks/useAuth";
import { useBillingPortal } from "@/hooks/useBillingPortal";
import { effectiveThemeColors } from "@/hooks/useColorTheme";
import { useCommunityPluginDetail } from "@/hooks/useCommunityPluginDetail";
import { useServer } from "@/hooks/useServer";
import { useTheme } from "@/hooks/useTheme";
import { showsCuratedCatalogueOnly } from "@/lib/marketplaceCuration";
import { embedAllow, pluginEmbeds } from "@/lib/pluginSurfaces";
import { getItem, setItem } from "@/lib/storage";
import { DEFAULT_THEME } from "@/lib/themes";
import { cn } from "@/lib/utils";
import { localized } from "@/lib/widgets/widgetMeta";

/** The message names an embed and this host agree on. */
const READY = "initiative-plugin:ready";
const HANDOFF = "initiative-plugin:handoff";
const ERROR = "initiative-plugin:error";
const LOCALE = "initiative-plugin:locale";
const THEME = "initiative-plugin:theme";

export interface CommunityPluginPageProps {
  pluginId: number;
  /**
   * The initiative this page is being read inside, if any. It selects the
   * surfaces on offer, and it travels to the plug-in in the minted token — so the
   * plug-in can scope what it shows without asking a second question.
   */
  initiativeId?: number;
}

export function CommunityPluginPage({ pluginId, initiativeId }: CommunityPluginPageProps) {
  const { t, i18n } = useTranslation(["plugins", "common"]);
  const communityId = useActiveCommunityId();
  const detail = useCommunityPluginDetail(pluginId);
  const plugin = detail.data;

  // Only the surfaces the server says this reader opens here.
  const embeds = useMemo(() => pluginEmbeds(plugin, initiativeId), [plugin, initiativeId]);
  const [surfaceId, setSurfaceId] = useState<string | null>(null);
  const active = embeds.find((embed) => embed.id === surfaceId) ?? embeds[0] ?? null;
  // The surface as a plain id, so a refetch that hands back an equal-but-new
  // definition does not read as a surface change and mint a token nobody asked
  // for.
  const activeId = active?.id ?? null;

  const { user } = useAuth();

  // The iPhone app says who a plug-in comes from before it first opens one
  // that Morelitea does not publish, and opens nothing until the member
  // continues.
  const { getServerOrigin } = useServer();
  const noticeKey = pluginNoticeKey(getServerOrigin() ?? "", user?.id ?? 0, communityId, pluginId);
  const [, noteAcknowledged] = useState(0);
  const held =
    Boolean(plugin) &&
    showsCuratedCatalogueOnly() &&
    !plugin?.listing?.first_party &&
    getItem(noticeKey) !== "1";
  const acknowledge = () => {
    void setItem(noticeKey, "1");
    noteAcknowledged((count) => count + 1);
  };

  const [handoff, setHandoff] = useState<CommunityPluginHandoff | null>(null);
  const [error, setError] = useState<string | null>(null);
  const iframeRef = useRef<HTMLIFrameElement | null>(null);
  // Whether the token we hold has already been handed over. A later `ready`
  // means the embed reloaded itself and the old token is spent, so the next
  // one is minted fresh.
  const spentRef = useRef(false);

  // Two routes, because where a surface was opened is the route's to say: the
  // initiative in the token is the one whose gate this request passed, not a
  // value the page hands over.
  const mint = useCallback(
    () =>
      (initiativeId === undefined
        ? createCommunityPluginHandoff(communityId, pluginId, activeId ?? "")
        : createInitiativePluginHandoff(
            communityId,
            initiativeId,
            pluginId,
            activeId ?? ""
          )) as unknown as Promise<CommunityPluginHandoff>,
    [communityId, initiativeId, pluginId, activeId]
  );

  // Mint for the surface being opened. Re-runs when the surface changes, which
  // is also when the iframe is replaced.
  useEffect(() => {
    if (!activeId || held) return;
    let cancelled = false;
    setHandoff(null);
    setError(null);
    spentRef.current = false;
    void mint()
      .then((fresh) => {
        if (!cancelled) setHandoff(fresh);
      })
      .catch(() => {
        if (!cancelled) setError(t("plugins:embed.handoffFailed"));
      });
    return () => {
      cancelled = true;
    };
  }, [activeId, held, mint, t]);

  const origin = useMemo(() => {
    if (!handoff?.embed_url) return null;
    try {
      return new URL(handoff.embed_url).origin;
    } catch {
      return null;
    }
  }, [handoff?.embed_url]);

  const allowed = useMemo(
    () => new Set(handoff?.allowed_origins ?? []),
    [handoff?.allowed_origins]
  );

  // The reader's appearance travels with the token so the embed opens already
  // wearing it: the resolved mode ("system" is resolved on this side — the
  // embed should follow this page, not re-derive the OS preference), and the
  // effective palette, since an iframe on another origin cannot read this
  // document's custom properties.
  const { resolvedTheme } = useTheme();
  const colorThemeId = user?.color_theme ?? DEFAULT_THEME;
  const themeColors = useMemo(
    () => effectiveThemeColors(colorThemeId, resolvedTheme),
    [colorThemeId, resolvedTheme]
  );

  // Hold the translator in a ref so a language change cannot re-attach the
  // listener mid-exchange. Same for the theme.
  const tRef = useRef(t);
  tRef.current = t;
  const localeRef = useRef(i18n.language);
  localeRef.current = i18n.language;
  const themeRef = useRef(resolvedTheme);
  themeRef.current = resolvedTheme;
  const themeColorsRef = useRef(themeColors);
  themeColorsRef.current = themeColors;
  // Asked at delivery rather than read at render: a phone's store may not
  // have answered yet when the frame announces itself.
  const { sellsNow } = useBillingPortal();
  const sellsNowRef = useRef(sellsNow);
  sellsNowRef.current = sellsNow;

  useEffect(() => {
    if (!origin || !handoff) return;

    // A token names one surface, and switching tabs replaces the iframe. So a
    // re-mint still in flight when that happens must not deliver: its token is
    // for the surface that was open when it was asked for, and the frame now
    // waiting shows a different one. Same plug-in, same origin, so the origin check
    // cannot tell them apart.
    let cancelled = false;

    const send = async (target: Window, token: CommunityPluginHandoff) => {
      const sells = await sellsNowRef.current();
      // Dropped if the surface changed, or the frame was replaced, meanwhile.
      if (cancelled || iframeRef.current?.contentWindow !== target) return;
      target.postMessage(
        {
          type: HANDOFF,
          handoff_token: token.handoff_token,
          expires_in_seconds: token.expires_in_seconds,
          audience: token.audience,
          surface_id: token.surface_id,
          locale: localeRef.current,
          theme: themeRef.current,
          theme_colors: themeColorsRef.current,
          sells,
        },
        // Never "*": that would hand the token to whatever happens to be
        // loaded in the frame.
        origin
      );
    };

    const onMessage = (event: MessageEvent) => {
      if (!allowed.has(event.origin)) return;
      // This page exchanges with one window: the frame it mounted. An
      // announcement is matched to it by window rather than by origin, since
      // a plug-in may hold more than one window at the same address.
      const target = iframeRef.current?.contentWindow;
      if (!target || event.source !== target) return;
      const data = event.data;
      if (!data || typeof data !== "object" || typeof data.type !== "string") return;

      if (data.type === READY) {
        const failed = () => {
          if (!cancelled) setError(tRef.current("plugins:embed.handoffFailed"));
        };
        if (!spentRef.current) {
          spentRef.current = true;
          send(target, handoff).catch(failed);
          return;
        }
        void mint()
          .then((fresh) => {
            // Dropped if the surface changed while this was in flight, or if
            // the frame that asked is no longer the mounted one.
            if (cancelled || iframeRef.current?.contentWindow !== target) return;
            return send(target, fresh);
          })
          .catch(() => {
            if (!cancelled) setError(tRef.current("plugins:embed.handoffFailed"));
          });
      } else if (data.type === ERROR) {
        setError(
          typeof data.message === "string" ? data.message : tRef.current("plugins:embed.failed")
        );
      }
    };

    window.addEventListener("message", onMessage);
    return () => {
      cancelled = true;
      window.removeEventListener("message", onMessage);
    };
  }, [origin, allowed, handoff, mint]);

  // Keep the embed in step with a language change.
  useEffect(() => {
    if (!origin) return;
    const target = iframeRef.current?.contentWindow;
    if (!target) return;
    target.postMessage({ type: LOCALE, locale: i18n.language }, origin);
  }, [origin, i18n.language]);

  // And with an appearance change — flipping light/dark (or the color theme)
  // recolors the embed in place.
  useEffect(() => {
    if (!origin) return;
    const target = iframeRef.current?.contentWindow;
    if (!target) return;
    target.postMessage({ type: THEME, theme: resolvedTheme, colors: themeColors }, origin);
  }, [origin, resolvedTheme, themeColors]);

  if (detail.isLoading) {
    return (
      <SkeletonRegion className="space-y-4">
        <SkeletonPillRow count={3} pillClassName="h-8 w-24" />
        <EditorSkeleton className="min-h-[60vh]" />
      </SkeletonRegion>
    );
  }

  if (!plugin) return <Notice title={t("plugins:embed.notFound")} />;
  if (!plugin.enabled) return <Notice title={t("plugins:embed.disabled", { name: plugin.name })} />;
  if (!plugin.available)
    return (
      <Notice
        title={t("plugins:embed.unavailable", { name: plugin.name })}
        description={t("plugins:embed.unavailableDescription")}
      />
    );
  // Anything but our own can be reported from here, on every platform.
  const reportable = plugin.listing?.first_party ? null : plugin.listing;
  const report = reportable ? (
    <ReportButton targetType="marketplace_listing" targetId={reportable.id} />
  ) : null;

  if (!active)
    return <Notice title={t("plugins:embed.noSurface", { name: plugin.name })} action={report} />;
  if (held)
    return (
      <PluginProviderNotice name={plugin.name} listing={plugin.listing} onContinue={acknowledge} />
    );
  if (error) return <Notice title={t("plugins:embed.failed")} description={error} />;

  return (
    <div className="flex h-full flex-col">
      {(embeds.length > 1 || reportable) && (
        <div className="flex shrink-0 items-center gap-1 border-b px-2">
          {embeds.length > 1 &&
            embeds.map((embed) => (
              <button
                key={embed.id}
                type="button"
                onClick={() => setSurfaceId(embed.id)}
                className={cn(
                  "border-b-2 px-3 py-2 text-sm",
                  embed.id === active.id
                    ? "border-primary font-medium"
                    : "border-transparent text-muted-foreground hover:text-foreground"
                )}
              >
                {localized(embed.name, i18n.language) || embed.id}
              </button>
            ))}
          {reportable && (
            <ReportButton
              targetType="marketplace_listing"
              targetId={reportable.id}
              className="ml-auto h-8 w-8"
            />
          )}
        </div>
      )}
      {handoff?.embed_url ? (
        <iframe
          // Keyed by surface so switching tabs mounts a fresh frame rather
          // than reusing one that already spent its token.
          key={active.id}
          ref={iframeRef}
          src={handoff.embed_url}
          title={plugin.name}
          className="block min-h-0 w-full flex-1 border-0 bg-background"
          // Notably absent: allow-top-navigation, allow-modals,
          // allow-popups-to-escape-sandbox.
          sandbox="allow-scripts allow-same-origin allow-forms allow-downloads"
          referrerPolicy="no-referrer"
          // Built from what this surface's manifest declared; empty when it
          // declared none.
          allow={embedAllow(active)}
        />
      ) : (
        <div className="flex flex-1 items-center gap-2 p-4 text-muted-foreground text-sm">
          <Loader2 className="h-4 w-4 animate-spin" />
          {t("plugins:embed.connecting")}
        </div>
      )}
    </div>
  );
}

function Notice({
  title,
  description,
  action,
}: {
  title: string;
  description?: string;
  action?: ReactNode;
}) {
  return (
    <Card>
      <CardHeader>
        <div className="flex items-center gap-1">
          <CardTitle>{title}</CardTitle>
          {action}
        </div>
        {description ? <CardDescription>{description}</CardDescription> : null}
      </CardHeader>
    </Card>
  );
}
