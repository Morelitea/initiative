import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";
import { Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useGuildPath } from "@/lib/guildUrl";
import { useAppConfig } from "@/hooks/useAppConfig";
import { useInitiatives } from "@/hooks/useInitiatives";
import { createAdvancedToolHandoffApiV1InitiativesInitiativeIdAdvancedToolHandoffPost } from "@/api/generated/initiatives/initiatives";
import type { AdvancedToolHandoffResponse } from "@/api/generated/initiativeAPI.schemas";

/**
 * Embeds the configured advanced-tool URL as an iframe under a specific
 * initiative.
 *
 * Security model (mirrors what the backend handoff endpoint enforces):
 *
 *   1. Page is only reachable when the runtime config exposes an
 *      `advanced_tool` block (otherwise the route renders an empty state).
 *   2. Backend handoff already verifies: AUTOMATIONS_URL configured,
 *      initiative exists in active guild, user is guild admin or initiative
 *      member, advanced_tool_enabled=true.
 *   3. The handoff token is delivered to the iframe via postMessage *only*
 *      to the iframe's expected origin. We never put it in the URL.
 *   4. Inbound postMessage handlers verify event.origin against the same
 *      expected origin before trusting any payload.
 *   5. The iframe is sandboxed with the minimum capabilities needed for
 *      a typical embedded SPA.
 */
export const AdvancedToolPage = () => {
  const { initiativeId: initiativeIdParam } = useParams({ strict: false }) as {
    initiativeId: string;
  };
  const parsedInitiativeId = Number(initiativeIdParam);
  const initiativeId = Number.isFinite(parsedInitiativeId) ? parsedInitiativeId : null;

  const { t, i18n } = useTranslation(["initiatives", "common"]);
  const gp = useGuildPath();

  const { advancedTool, isLoading: configLoading } = useAppConfig();
  const initiativesQuery = useInitiatives({ enabled: initiativeId !== null });
  const initiative = useMemo(
    () =>
      initiativesQuery.data && initiativeId !== null
        ? (initiativesQuery.data.find((i) => i.id === initiativeId) ?? null)
        : null,
    [initiativesQuery.data, initiativeId]
  );

  // Outbound postMessage targetOrigin = the iframe's own origin (derived
  // from the configured URL). We never broadcast to "*" — that would leak
  // the handoff token to whatever origin happens to be loaded in the
  // iframe's window slot.
  const iframeOrigin = useMemo(() => {
    if (!advancedTool?.url) return null;
    try {
      return new URL(advancedTool.url).origin;
    } catch {
      return null;
    }
  }, [advancedTool?.url]);

  // Inbound postMessage allowlist comes from the runtime config (operator
  // can extend it via ADVANCED_TOOL_ALLOWED_ORIGINS). Backend always
  // includes the iframe URL's origin as the first entry, so the strict
  // ``Set`` lookup matches today's behavior when nothing extra is
  // configured.
  const allowedOrigins = useMemo(
    () => new Set(advancedTool?.allowed_origins ?? []),
    [advancedTool?.allowed_origins]
  );

  const iframeRef = useRef<HTMLIFrameElement | null>(null);
  const handoffRef = useRef<AdvancedToolHandoffResponse | null>(null);
  // Hold the latest ``t`` in a ref so the handoff effect can localize an
  // error without listing ``t`` in its deps. Without this, ``t`` changes
  // identity on every language switch (react-i18next behavior), which
  // would otherwise cancel the in-flight handoff fetch and re-mint a
  // fresh token even though the token itself has no locale dependency.
  const tRef = useRef(t);
  tRef.current = t;
  const [error, setError] = useState<string | null>(null);
  const [isReady, setIsReady] = useState(false);

  // Mint a fresh handoff token whenever we re-render the iframe. The token
  // is short-lived (60s) so we re-fetch on every mount instead of caching.
  useEffect(() => {
    let cancelled = false;
    if (initiativeId === null || !advancedTool || !iframeOrigin) return;

    setError(null);
    setIsReady(false);

    void (async () => {
      try {
        const response =
          (await createAdvancedToolHandoffApiV1InitiativesInitiativeIdAdvancedToolHandoffPost(
            initiativeId
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
  }, [initiativeId, advancedTool, iframeOrigin]);

  // postMessage bridge: the iframe sends `ready` when it's listening, and
  // `error` if its own bootstrap fails. We strictly verify event.origin on
  // every inbound message — missing this check is the canonical
  // iframe-token-leak vulnerability.
  useEffect(() => {
    if (!iframeOrigin) return;

    const handleMessage = (event: MessageEvent) => {
      if (!allowedOrigins.has(event.origin)) return;
      const data = event.data;
      if (!data || typeof data !== "object" || typeof data.type !== "string") return;

      if (data.type === "advanced-tool:ready") {
        // The iframe is listening — hand the token over, scoped strictly
        // to the iframe's origin (never "*"). Locale is included so the
        // embedded app renders in the same language as the parent without
        // forcing the user to set it twice; the embed is free to ignore
        // it or let the user override later.
        const handoff = handoffRef.current;
        const target = iframeRef.current?.contentWindow;
        if (handoff && target) {
          // Envelope mirrors SettingsGuildAdvancedToolPage so the embed
          // can rely on a single message shape across scopes — scope and
          // initiative_id are always present (initiative_id is null at
          // guild scope), so the embed never has to decode the JWT just
          // to learn which view to render.
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

  // If the user switches language while the iframe is open, push the new
  // locale into the embed so it can re-render. The iframe is free to debounce
  // or ignore; the SPA's job is just to keep it informed.
  useEffect(() => {
    if (!iframeOrigin) return;
    const target = iframeRef.current?.contentWindow;
    if (!target || !isReady) return;
    target.postMessage({ type: "advanced-tool:locale", locale: i18n.language }, iframeOrigin);
  }, [iframeOrigin, isReady, i18n.language]);

  if (configLoading || initiativesQuery.isLoading) {
    return (
      <div className="text-muted-foreground flex items-center gap-2 text-sm">
        <Loader2 className="h-4 w-4 animate-spin" />
        {t("common:loading")}
      </div>
    );
  }

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

  if (initiativeId === null || !initiative) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>{t("settings.notFound")}</CardTitle>
          <CardDescription>{t("settings.notFoundDescription")}</CardDescription>
        </CardHeader>
      </Card>
    );
  }

  if (!initiative.advanced_tool_enabled) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>{t("advancedTool.disabledTitle", { name: advancedTool.name })}</CardTitle>
          <CardDescription>{t("advancedTool.disabledDescription")}</CardDescription>
        </CardHeader>
        <div className="px-6 pb-6">
          <Button asChild variant="outline">
            <Link to={gp(`/initiatives/${initiative.id}/settings`)}>
              {t("advancedTool.openSettings")}
            </Link>
          </Button>
        </div>
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

  // The parent <main> has `container mx-auto` which caps width at a
  // breakpoint-driven max — negative margins alone don't escape that.
  // We position the iframe wrapper fixed to the viewport, offset by the
  // 3rem sticky header on top and the 20rem sidebar on desktop. On mobile
  // the sidebar is offcanvas, so the wrapper extends edge-to-edge.
  //
  // The iframe URL has NO secrets in it — only the initiative id. The
  // handoff token is delivered via postMessage after the iframe sends
  // its `ready` signal, so it never lands in browser history, proxy
  // logs, or referrer headers.
  return (
    <div className="fixed inset-x-0 top-12 bottom-0 md:left-[var(--sidebar-width,20rem)]">
      <iframe
        ref={iframeRef}
        src={`${advancedTool.url}/embed/${initiative.id}`}
        title={advancedTool.name}
        className="bg-background block h-full w-full border-0"
        // Minimum capabilities for an embedded SPA. Notably absent:
        // allow-top-navigation (would let the iframe redirect the parent),
        // allow-popups-to-escape-sandbox, allow-modals (re-enable only if
        // the embed actually needs them).
        sandbox="allow-scripts allow-same-origin allow-forms allow-downloads"
        // No referrer leaks the parent path/query into the iframe.
        referrerPolicy="no-referrer"
        // Prevents the iframe from being abused as a feature gateway by
        // disabling powerful APIs that aren't needed for an embedded UI.
        allow="clipboard-read; clipboard-write"
      />
    </div>
  );
};
