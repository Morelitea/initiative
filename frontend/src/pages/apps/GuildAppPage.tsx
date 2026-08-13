/**
 * An app's own surface, in an iframe.
 *
 * The security shape, which mirrors what the mint endpoint already enforces:
 *
 * 1. The server decides whether a surface may be opened — the install must be
 *    enabled, its registration live, and the manifest's `visibility` must admit
 *    the caller. A refusal never reaches the app.
 * 2. The token is delivered by `postMessage` to the iframe's own origin, never
 *    in the URL, so it stays out of history, referrers and proxy logs.
 * 3. Inbound messages are ignored unless `event.origin` is one the registration
 *    listed.
 * 4. The token is one-shot, so a reloading embed asks again and gets a fresh
 *    one rather than being stuck until the page is reloaded.
 */

import { Loader2 } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { createGuildAppHandoffApiV1GGuildIdAppsAppIdHandoffSurfaceIdPost } from "@/api/generated/apps/apps";
import type { GuildAppHandoff } from "@/api/generated/initiativeAPI.schemas";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useActiveGuildId } from "@/hooks/useActiveGuildId";
import { useGuildAppDetail } from "@/hooks/useGuildAppDetail";
import { appEmbeds } from "@/lib/appSurfaces";
import { cn } from "@/lib/utils";
import { localized } from "@/lib/widgets/widgetMeta";

/** The message names an embed and this host agree on. */
const READY = "initiative-app:ready";
const HANDOFF = "initiative-app:handoff";
const ERROR = "initiative-app:error";
const LOCALE = "initiative-app:locale";

export function GuildAppPage({ appId }: { appId: number }) {
  const { t, i18n } = useTranslation(["apps", "common"]);
  const guildId = useActiveGuildId();
  const detail = useGuildAppDetail(appId);
  const app = detail.data;

  const embeds = useMemo(() => appEmbeds(app?.definition), [app?.definition]);
  const [surfaceId, setSurfaceId] = useState<string | null>(null);
  const active = embeds.find((embed) => embed.id === surfaceId) ?? embeds[0] ?? null;
  // The surface as a plain id, so a refetch that hands back an equal-but-new
  // definition does not read as a surface change and mint a token nobody asked
  // for.
  const activeId = active?.id ?? null;

  const [handoff, setHandoff] = useState<GuildAppHandoff | null>(null);
  const [error, setError] = useState<string | null>(null);
  const iframeRef = useRef<HTMLIFrameElement | null>(null);
  // Whether the token we hold has already been handed over. A later `ready`
  // means the embed reloaded itself and the old token is spent, so the next
  // one is minted fresh.
  const spentRef = useRef(false);

  const mint = useCallback(
    () =>
      createGuildAppHandoffApiV1GGuildIdAppsAppIdHandoffSurfaceIdPost(
        guildId,
        appId,
        activeId ?? ""
      ) as unknown as Promise<GuildAppHandoff>,
    [guildId, appId, activeId]
  );

  // Mint for the surface being opened. Re-runs when the surface changes, which
  // is also when the iframe is replaced.
  useEffect(() => {
    if (!activeId) return;
    let cancelled = false;
    setHandoff(null);
    setError(null);
    spentRef.current = false;
    void mint()
      .then((fresh) => {
        if (!cancelled) setHandoff(fresh);
      })
      .catch(() => {
        if (!cancelled) setError(t("apps:embed.handoffFailed"));
      });
    return () => {
      cancelled = true;
    };
  }, [activeId, mint, t]);

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

  // Hold the translator in a ref so a language change cannot re-attach the
  // listener mid-exchange.
  const tRef = useRef(t);
  tRef.current = t;
  const localeRef = useRef(i18n.language);
  localeRef.current = i18n.language;

  useEffect(() => {
    if (!origin || !handoff) return;

    // A token names one surface, and switching tabs replaces the iframe. So a
    // re-mint still in flight when that happens must not deliver: its token is
    // for the surface that was open when it was asked for, and the frame now
    // waiting shows a different one. Same app, same origin, so the origin check
    // cannot tell them apart.
    let cancelled = false;

    const send = (target: Window, token: GuildAppHandoff) => {
      target.postMessage(
        {
          type: HANDOFF,
          handoff_token: token.handoff_token,
          expires_in_seconds: token.expires_in_seconds,
          audience: token.audience,
          surface_id: token.surface_id,
          locale: localeRef.current,
        },
        // Never "*": that would hand the token to whatever happens to be
        // loaded in the frame.
        origin
      );
    };

    const onMessage = (event: MessageEvent) => {
      if (!allowed.has(event.origin)) return;
      const data = event.data;
      if (!data || typeof data !== "object" || typeof data.type !== "string") return;

      if (data.type === READY) {
        const target = iframeRef.current?.contentWindow;
        if (!target) return;
        if (!spentRef.current) {
          send(target, handoff);
          spentRef.current = true;
          return;
        }
        void mint()
          .then((fresh) => {
            // Dropped if the surface changed while this was in flight, or if
            // the frame that asked is no longer the mounted one.
            if (cancelled || iframeRef.current?.contentWindow !== target) return;
            send(target, fresh);
          })
          .catch(() => {
            if (!cancelled) setError(tRef.current("apps:embed.handoffFailed"));
          });
      } else if (data.type === ERROR) {
        setError(
          typeof data.message === "string" ? data.message : tRef.current("apps:embed.failed")
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

  if (detail.isLoading) {
    return (
      <div className="flex items-center gap-2 text-muted-foreground text-sm">
        <Loader2 className="h-4 w-4 animate-spin" />
        {t("common:loading")}
      </div>
    );
  }

  if (!app) return <Notice title={t("apps:embed.notFound")} />;
  if (!app.enabled) return <Notice title={t("apps:embed.disabled", { name: app.name })} />;
  if (!app.available)
    return (
      <Notice
        title={t("apps:embed.unavailable", { name: app.name })}
        description={t("apps:embed.unavailableDescription")}
      />
    );
  if (!active) return <Notice title={t("apps:embed.noSurface", { name: app.name })} />;
  if (error) return <Notice title={t("apps:embed.failed")} description={error} />;

  return (
    <div className="flex h-full flex-col">
      {embeds.length > 1 && (
        <div className="flex shrink-0 gap-1 border-b px-2">
          {embeds.map((embed) => (
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
        </div>
      )}
      {handoff?.embed_url ? (
        <iframe
          // Keyed by surface so switching tabs mounts a fresh frame rather
          // than reusing one that already spent its token.
          key={active.id}
          ref={iframeRef}
          src={handoff.embed_url}
          title={app.name}
          className="block h-full w-full flex-1 border-0 bg-background"
          // Notably absent: allow-top-navigation, allow-modals,
          // allow-popups-to-escape-sandbox.
          sandbox="allow-scripts allow-same-origin allow-forms allow-downloads"
          referrerPolicy="no-referrer"
          allow="clipboard-read; clipboard-write"
        />
      ) : (
        <div className="flex flex-1 items-center gap-2 p-4 text-muted-foreground text-sm">
          <Loader2 className="h-4 w-4 animate-spin" />
          {t("apps:embed.connecting")}
        </div>
      )}
    </div>
  );
}

function Notice({ title, description }: { title: string; description?: string }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
        {description ? <CardDescription>{description}</CardDescription> : null}
      </CardHeader>
    </Card>
  );
}
