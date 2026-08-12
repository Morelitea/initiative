/**
 * An installed app's own surface.
 *
 * Apps that mount a tool link straight at that tool and never come here — a
 * guild calendar is a calendar, rendered by the calendar. This page is for the
 * other shape: an app that opens a surface the operator configured, which has
 * no route of its own to link to.
 *
 * The embed itself is the machinery that used to live in guild settings, moved
 * rather than rebuilt: the backend mints the handoff, it reaches the iframe by
 * postMessage, and inbound messages are matched against the operator's origin
 * allowlist.
 */

import { useParams } from "@tanstack/react-router";
import { Loader2 } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { createGuildAdvancedToolHandoffApiV1GuildsGuildIdAdvancedToolHandoffPost } from "@/api/generated/guilds/guilds";
import type {
  AdvancedToolHandoffResponse,
  GuildAppRead,
} from "@/api/generated/initiativeAPI.schemas";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useActiveGuildId } from "@/hooks/useActiveGuildId";
import { useAppConfig } from "@/hooks/useAppConfig";
import { useGuildApps } from "@/hooks/useGuildApps";
import { useGuilds } from "@/hooks/useGuilds";

export const GuildAppPage = () => {
  const { t } = useTranslation(["apps", "initiatives", "common"]);
  const { appId: appIdParam } = useParams({ strict: false }) as { appId?: string };
  const appId = Number(appIdParam);
  const appsQuery = useGuildApps();

  const app = useMemo(
    () => appsQuery.data?.items.find((item) => item.id === appId) ?? null,
    [appsQuery.data, appId]
  );

  if (appsQuery.isLoading) {
    return (
      <div className="flex items-center gap-2 text-muted-foreground text-sm">
        <Loader2 className="h-4 w-4 animate-spin" />
        {t("common:loading")}
      </div>
    );
  }

  if (!app?.enabled) {
    // Turned off reads the same as gone: an admin turns it back on in guild
    // settings, and until then there is nothing here to show.
    return (
      <Card>
        <CardHeader>
          <CardTitle>{t("apps:page.notFound")}</CardTitle>
          <CardDescription>{t("apps:page.notFoundDescription")}</CardDescription>
        </CardHeader>
      </Card>
    );
  }

  if (app.embed_target === "advanced_tool") {
    return <AdvancedToolEmbed app={app} />;
  }

  // An app kind this build has no surface for. Reachable only by editing the
  // URL, since nothing links here for one.
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("apps:page.noSurface", { name: app.name })}</CardTitle>
        <CardDescription>{t("apps:page.noSurfaceDescription")}</CardDescription>
      </CardHeader>
    </Card>
  );
};

/**
 * The deployment's configured advanced tool, at guild scope.
 *
 * Guild admins only, which the backend handoff endpoint enforces; this renders
 * the empty state rather than an iframe that would fail to load.
 */
const AdvancedToolEmbed = ({ app }: { app: GuildAppRead }) => {
  const { t, i18n } = useTranslation(["initiatives", "common"]);
  const { activeGuild } = useGuilds();
  const guildId = useActiveGuildId();
  const isGuildAdmin = activeGuild?.role === "admin";

  const { advancedTool, isLoading: configLoading } = useAppConfig();

  // Outbound postMessage goes to the iframe's own origin, derived from the
  // configured URL.
  const iframeOrigin = useMemo(() => {
    if (!advancedTool?.url) return null;
    try {
      return new URL(advancedTool.url).origin;
    } catch {
      return null;
    }
  }, [advancedTool?.url]);

  // Inbound allowlist = the operator-configured set, which always includes the
  // iframe URL's origin as its first entry.
  const allowedOrigins = useMemo(
    () => new Set(advancedTool?.allowed_origins ?? []),
    [advancedTool?.allowed_origins]
  );

  const iframeRef = useRef<HTMLIFrameElement | null>(null);
  const handoffRef = useRef<AdvancedToolHandoffResponse | null>(null);
  // See AdvancedToolPage for the rationale on these refs:
  // - handoffSentRef: tracks first-vs-subsequent ``advanced-tool:ready`` so a
  //   fresh token is minted if the embed reloads itself (the cached one has
  //   been redeemed by then).
  // - tRef / localeRef: hold the latest values without re-attaching the
  //   listener, which would cancel any in-flight re-mint.
  const handoffSentRef = useRef(false);
  const tRef = useRef(t);
  tRef.current = t;
  const localeRef = useRef(i18n.language);
  localeRef.current = i18n.language;
  const [error, setError] = useState<string | null>(null);
  const [isReady, setIsReady] = useState(false);

  // Mint a fresh handoff on mount. Short-lived, so re-fetched rather than
  // cached across mounts.
  useEffect(() => {
    let cancelled = false;
    if (guildId === null || !advancedTool || !iframeOrigin || !isGuildAdmin) return;

    setError(null);
    setIsReady(false);
    handoffSentRef.current = false;

    void (async () => {
      try {
        const response =
          (await createGuildAdvancedToolHandoffApiV1GuildsGuildIdAdvancedToolHandoffPost(
            guildId
          )) as unknown as AdvancedToolHandoffResponse;
        if (cancelled) return;
        handoffRef.current = response;
        setIsReady(true);
      } catch {
        if (!cancelled) {
          setError(tRef.current("advancedTool.handoffFailed"));
        }
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [guildId, advancedTool, iframeOrigin, isGuildAdmin]);

  // postMessage bridge. Every inbound message is matched against the allowlist
  // before it is read.
  useEffect(() => {
    if (!iframeOrigin || guildId === null) return;

    // initiative_id is forwarded as null at guild scope so the envelope shape
    // stays identical to the initiative-scoped handoff and the embed can
    // dispatch on a single message type.
    const postHandoff = (target: Window, handoff: AdvancedToolHandoffResponse) => {
      target.postMessage(
        {
          type: "advanced-tool:handoff",
          handoff_token: handoff.handoff_token,
          expires_in_seconds: handoff.expires_in_seconds,
          scope: handoff.scope,
          initiative_id: handoff.initiative_id,
          locale: localeRef.current,
        },
        iframeOrigin
      );
    };

    const handleMessage = (event: MessageEvent) => {
      if (!allowedOrigins.has(event.origin)) return;
      const data = event.data;
      if (!data || typeof data !== "object" || typeof data.type !== "string") return;

      if (data.type === "advanced-tool:ready") {
        const target = iframeRef.current?.contentWindow;
        if (!target) return;

        // First ready: the cached token from the initial mint. A later ready
        // means the embed reloaded itself and that token is spent, so mint
        // fresh — otherwise recovery needs a reload of the parent page.
        if (!handoffSentRef.current && handoffRef.current) {
          postHandoff(target, handoffRef.current);
          handoffSentRef.current = true;
          return;
        }

        void (async () => {
          try {
            const fresh =
              (await createGuildAdvancedToolHandoffApiV1GuildsGuildIdAdvancedToolHandoffPost(
                guildId
              )) as unknown as AdvancedToolHandoffResponse;
            handoffRef.current = fresh;
            postHandoff(target, fresh);
          } catch {
            setError(tRef.current("advancedTool.handoffFailed"));
          }
        })();
      } else if (data.type === "advanced-tool:error") {
        setError(
          typeof data.message === "string" ? data.message : tRef.current("advancedTool.iframeError")
        );
      }
    };

    window.addEventListener("message", handleMessage);
    return () => window.removeEventListener("message", handleMessage);
  }, [iframeOrigin, allowedOrigins, guildId]);

  // Push locale changes through to the embed. It is free to ignore them.
  useEffect(() => {
    if (!iframeOrigin) return;
    const target = iframeRef.current?.contentWindow;
    if (!target || !isReady) return;
    target.postMessage({ type: "advanced-tool:locale", locale: i18n.language }, iframeOrigin);
  }, [iframeOrigin, isReady, i18n.language]);

  if (configLoading) {
    return (
      <div className="flex items-center gap-2 text-muted-foreground text-sm">
        <Loader2 className="h-4 w-4 animate-spin" />
        {t("common:loading")}
      </div>
    );
  }

  // The listing is withdrawn when the deployment stops being configured, but an
  // app installed while it was stays installed — so this state is reachable and
  // says what happened rather than showing a blank frame.
  if (!advancedTool || !iframeOrigin) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>{t("advancedTool.unavailableTitle")}</CardTitle>
          <CardDescription>{t("advancedTool.unavailableDescription")}</CardDescription>
        </CardHeader>
      </Card>
    );
  }

  if (!isGuildAdmin || guildId === null) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>{t("advancedTool.guildAdminOnlyTitle")}</CardTitle>
          <CardDescription>{t("advancedTool.guildAdminOnlyDescription")}</CardDescription>
        </CardHeader>
      </Card>
    );
  }

  if (error) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>{t("advancedTool.iframeError")}</CardTitle>
          <CardDescription>{error}</CardDescription>
        </CardHeader>
      </Card>
    );
  }

  if (!isReady) {
    return (
      <div className="flex items-center gap-2 text-muted-foreground text-sm">
        <Loader2 className="h-4 w-4 animate-spin" />
        {t("advancedTool.connecting")}
      </div>
    );
  }

  // Full-bleed, like the initiative-scoped embed: this is the app's whole
  // surface now rather than the contents of a settings tab. Offset by the
  // sticky header and, on desktop, the sidebar.
  //
  // ``?scope=guild`` tells the receiving service which view to render. The
  // scope it acts on comes from the signed token's claim.
  return (
    <div className="fixed inset-x-0 top-12 bottom-0 md:left-[var(--sidebar-width,20rem)]">
      <iframe
        ref={iframeRef}
        src={`${advancedTool.url}/embed?scope=guild`}
        title={app.name}
        className="block h-full w-full border-0 bg-background"
        // Minimum capabilities for an embedded SPA.
        sandbox="allow-scripts allow-same-origin allow-forms allow-downloads"
        referrerPolicy="no-referrer"
        allow="clipboard-read; clipboard-write"
      />
    </div>
  );
};
