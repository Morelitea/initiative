import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Loader2 } from "lucide-react";

import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useAppConfig } from "@/hooks/useAppConfig";
import { useGuilds } from "@/hooks/useGuilds";
import { createGuildAdvancedToolHandoffApiV1GuildsGuildIdAdvancedToolHandoffPost } from "@/api/generated/guilds/guilds";
import type { AdvancedToolHandoffResponse } from "@/api/generated/initiativeAPI.schemas";

/**
 * Guild-scoped advanced-tool embed.
 *
 * Mirrors the initiative-scoped page but for guild admins. The URL exposes
 * a ``scope=guild`` query param as a routing hint — the proprietary embed
 * MUST trust the JWT's ``scope`` claim, not this param. The param exists
 * solely to help the receiving service render the right view when the
 * token is also present.
 *
 * Authorization checks happen on the backend handoff endpoint (admin-only,
 * configured-only). This component renders a "not configured" empty state
 * if the runtime config doesn't expose an advanced tool, and a loading
 * spinner while the handoff is being minted.
 */
export const SettingsGuildAdvancedToolPage = () => {
  const { t, i18n } = useTranslation(["initiatives", "common"]);
  const { activeGuild, activeGuildId } = useGuilds();
  const isGuildAdmin = activeGuild?.role === "admin";

  const { advancedTool, isLoading: configLoading } = useAppConfig();

  // Outbound postMessage target = iframe's own origin (from configured URL).
  // Inbound allowlist = the operator-configured set from runtime config,
  // which always includes the iframe URL origin as the first entry.
  const iframeOrigin = useMemo(() => {
    if (!advancedTool?.url) return null;
    try {
      return new URL(advancedTool.url).origin;
    } catch {
      return null;
    }
  }, [advancedTool?.url]);

  const allowedOrigins = useMemo(
    () => new Set(advancedTool?.allowed_origins ?? []),
    [advancedTool?.allowed_origins]
  );

  const iframeRef = useRef<HTMLIFrameElement | null>(null);
  const handoffRef = useRef<AdvancedToolHandoffResponse | null>(null);
  // See AdvancedToolPage: hold the latest ``t`` in a ref so the handoff
  // effect can localize errors without re-firing on every language change.
  const tRef = useRef(t);
  tRef.current = t;
  const [error, setError] = useState<string | null>(null);
  const [isReady, setIsReady] = useState(false);

  // Mint a fresh handoff token on mount. Short-lived (60s) so re-fetched
  // on every render rather than cached.
  useEffect(() => {
    let cancelled = false;
    if (activeGuildId === null || !advancedTool || !iframeOrigin || !isGuildAdmin) return;

    setError(null);
    setIsReady(false);

    void (async () => {
      try {
        const response =
          (await createGuildAdvancedToolHandoffApiV1GuildsGuildIdAdvancedToolHandoffPost(
            activeGuildId
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
  }, [activeGuildId, advancedTool, iframeOrigin, isGuildAdmin]);

  // postMessage bridge — strict origin check on every inbound message.
  useEffect(() => {
    if (!iframeOrigin) return;

    const handleMessage = (event: MessageEvent) => {
      if (!allowedOrigins.has(event.origin)) return;
      const data = event.data;
      if (!data || typeof data !== "object" || typeof data.type !== "string") return;

      if (data.type === "advanced-tool:ready") {
        const handoff = handoffRef.current;
        const target = iframeRef.current?.contentWindow;
        if (handoff && target) {
          // initiative_id is forwarded as null at guild scope so the
          // envelope shape stays identical to the initiative-scoped
          // handoff and the embed can dispatch on a single message type.
          target.postMessage(
            {
              type: "advanced-tool:handoff",
              handoff_token: handoff.handoff_token,
              expires_in_seconds: handoff.expires_in_seconds,
              scope: handoff.scope,
              initiative_id: handoff.initiative_id,
              locale: i18n.language,
            },
            iframeOrigin
          );
        }
      } else if (data.type === "advanced-tool:error") {
        setError(typeof data.message === "string" ? data.message : t("advancedTool.iframeError"));
      }
    };

    window.addEventListener("message", handleMessage);
    return () => window.removeEventListener("message", handleMessage);
  }, [iframeOrigin, allowedOrigins, t, i18n.language]);

  // Push locale changes through to the embed (matches the initiative-scoped
  // page). Embed is free to ignore.
  useEffect(() => {
    if (!iframeOrigin) return;
    const target = iframeRef.current?.contentWindow;
    if (!target || !isReady) return;
    target.postMessage({ type: "advanced-tool:locale", locale: i18n.language }, iframeOrigin);
  }, [iframeOrigin, isReady, i18n.language]);

  if (configLoading) {
    return (
      <div className="text-muted-foreground flex items-center gap-2 text-sm">
        <Loader2 className="h-4 w-4 animate-spin" />
        {t("common:loading")}
      </div>
    );
  }

  // The tab is gated by GuildSettingsLayout, but defensively re-check both
  // gates here so a deep link can never bypass the empty states.
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

  if (!isGuildAdmin || activeGuildId === null) {
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
      <div className="text-muted-foreground flex items-center gap-2 text-sm">
        <Loader2 className="h-4 w-4 animate-spin" />
        {t("advancedTool.connecting")}
      </div>
    );
  }

  // Renders inside the guild settings tab content — NOT full-screen. The
  // iframe height fills most of the visible viewport but leaves the page
  // header, tabs, and main padding intact above it. ``min-h`` keeps it
  // usable on short windows where the calc would otherwise crush it.
  // ``?scope=guild`` is a routing hint — the proprietary backend MUST also
  // verify the JWT's scope claim. Without the signed token, the param is
  // useless.
  return (
    <iframe
      ref={iframeRef}
      src={`${advancedTool.url}/embed?scope=guild`}
      title={advancedTool.name}
      className="bg-background block h-[calc(100dvh-22rem)] min-h-[500px] w-full rounded-md border"
      sandbox="allow-scripts allow-same-origin allow-forms allow-downloads"
      referrerPolicy="no-referrer"
      allow="clipboard-read; clipboard-write"
    />
  );
};
