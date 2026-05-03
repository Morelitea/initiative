import { useEffect, useRef, useState } from "react";

import type { CaptchaConfig } from "@/api/generated/initiativeAPI.schemas";

/**
 * Single captcha widget that swaps between hCaptcha, Cloudflare
 * Turnstile and Google reCAPTCHA based on the runtime config served
 * by ``GET /api/v1/config``. Only one provider is active per
 * deployment — the one the operator configured via
 * ``CAPTCHA_PROVIDER``.
 *
 * The provider's JS is loaded on demand (a single ``<script>`` tag
 * appended to ``<head>`` once per page load, deduped by URL) so the
 * default OSS deployment with no captcha never pulls vendor JS.
 *
 * On a successful solve the widget calls ``onToken(token)``; on
 * expiry / error / reset it calls ``onToken("")`` so the parent form
 * can re-disable submit. The parent owns the token state — this
 * component is a pure render adapter.
 */

interface CaptchaWidgetProps {
  config: CaptchaConfig;
  onToken: (token: string) => void;
}

const PROVIDER_SCRIPT_URL: Record<string, string> = {
  // ``render=explicit`` (hCaptcha + reCAPTCHA) and ``onload`` give us
  // a deterministic init point so the SDK doesn't auto-render any
  // accidental ``.h-captcha`` / ``.g-recaptcha`` markup elsewhere on
  // the page. Turnstile already requires explicit render via API.
  hcaptcha: "https://js.hcaptcha.com/1/api.js?render=explicit",
  turnstile: "https://challenges.cloudflare.com/turnstile/v0/api.js",
  recaptcha: "https://www.google.com/recaptcha/api.js?render=explicit",
};

interface ProviderRenderApi {
  /** Each SDK exposes a ``render(container, opts)`` that returns an
   *  opaque widget id; we hold on to it for the cleanup path. */
  render: (
    container: HTMLElement,
    opts: {
      sitekey: string;
      callback: (token: string) => void;
      "expired-callback"?: () => void;
      "error-callback"?: () => void;
    }
  ) => string | number;
  /** Reset the rendered widget by id. All three SDKs ship this. */
  reset: (widgetId?: string | number) => void;
}

type WindowWithCaptchas = Window & {
  hcaptcha?: ProviderRenderApi;
  turnstile?: ProviderRenderApi;
  grecaptcha?: ProviderRenderApi;
};

const getProviderApi = (provider: string): ProviderRenderApi | undefined => {
  const w = window as WindowWithCaptchas;
  if (provider === "hcaptcha") return w.hcaptcha;
  if (provider === "turnstile") return w.turnstile;
  if (provider === "recaptcha") return w.grecaptcha;
  return undefined;
};

/** Inject the provider script once per page-load. Subsequent calls
 *  resolve immediately if the SDK global is already present. */
const loadScript = (url: string): Promise<void> =>
  new Promise((resolve, reject) => {
    if (document.querySelector(`script[data-captcha-src="${url}"]`)) {
      resolve();
      return;
    }
    const el = document.createElement("script");
    el.src = url;
    el.async = true;
    el.defer = true;
    el.dataset.captchaSrc = url;
    el.onload = () => resolve();
    el.onerror = () => reject(new Error(`Failed to load captcha script: ${url}`));
    document.head.appendChild(el);
  });

export const CaptchaWidget = ({ config, onToken }: CaptchaWidgetProps) => {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const widgetIdRef = useRef<string | number | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const scriptUrl = PROVIDER_SCRIPT_URL[config.provider];
    if (!scriptUrl) {
      // Unknown provider name — should be impossible because the
      // backend filters to the supported list, but bail out cleanly.
      setError(`Unknown captcha provider: ${config.provider}`);
      return;
    }

    loadScript(scriptUrl)
      .then(() => {
        // Poll for the SDK to finish initialising. ``script.onload``
        // can fire a tick before the global is observable, and for
        // Google reCAPTCHA there's a longer gap: ``window.grecaptcha``
        // is set to a small bootstrap object with only ``.ready``
        // before the rest of the SDK loads, and ``.render`` only
        // attaches once initialisation finishes. Wait for ``.render``
        // specifically so we don't race that gap.
        const start = Date.now();
        const poll = () => {
          if (cancelled) return;
          const api = getProviderApi(config.provider);
          if (api && typeof api.render === "function") {
            if (!containerRef.current) return;
            try {
              widgetIdRef.current = api.render(containerRef.current, {
                sitekey: config.site_key,
                callback: (token: string) => onToken(token),
                "expired-callback": () => onToken(""),
                "error-callback": () => onToken(""),
              });
            } catch (renderErr) {
              setError(renderErr instanceof Error ? renderErr.message : "Captcha render failed");
            }
            return;
          }
          if (Date.now() - start > 5000) {
            setError("Captcha SDK didn't load in time. Refresh the page.");
            return;
          }
          window.setTimeout(poll, 50);
        };
        poll();
      })
      .catch((scriptErr: Error) => {
        if (cancelled) return;
        setError(scriptErr.message);
      });

    return () => {
      cancelled = true;
      const api = getProviderApi(config.provider);
      if (api && widgetIdRef.current !== null) {
        try {
          api.reset(widgetIdRef.current);
        } catch {
          // Best effort — provider SDKs sometimes throw on reset of
          // an already-removed widget. Nothing actionable for the user.
        }
      }
      widgetIdRef.current = null;
    };
  }, [config.provider, config.site_key, onToken]);

  if (error) {
    return <p className="text-destructive text-sm">{error}</p>;
  }

  return <div ref={containerRef} />;
};
