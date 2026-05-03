"""Server-side verification for the registration captcha.

Three providers are supported, selected via the ``CAPTCHA_PROVIDER``
env var:

  - ``"hcaptcha"``    → https://hcaptcha.com/
  - ``"turnstile"``   → Cloudflare Turnstile
  - ``"recaptcha"``   → Google reCAPTCHA v2/v3 (verify endpoint is
                        the same for both versions; v3 score is not
                        gated here — set a low threshold via the
                        provider's own console if you need one).

All three accept the same form-encoded POST shape (``secret``,
``response``, optional ``remoteip``) and return JSON with
``success: bool``. The helper is provider-agnostic above that.

Silent disable: when ``CAPTCHA_PROVIDER`` / ``CAPTCHA_SECRET_KEY``
isn't configured, ``verify_or_raise`` is a no-op so registration
works exactly as before. The register endpoint also short-circuits
on the bootstrap-first-user path so a fresh deployment isn't blocked
by a captcha it hasn't been told to require.
"""
from __future__ import annotations

import logging

import httpx
from fastapi import HTTPException, status

from app.core.config import settings
from app.core.messages import AuthMessages

logger = logging.getLogger(__name__)


# Provider → siteverify URL. Names match the public ``CAPTCHA_PROVIDER``
# env value so operators can read the var and immediately know what's
# being called.
_VERIFY_URLS: dict[str, str] = {
    "hcaptcha": "https://hcaptcha.com/siteverify",
    "turnstile": "https://challenges.cloudflare.com/turnstile/v0/siteverify",
    "recaptcha": "https://www.google.com/recaptcha/api/siteverify",
}


def is_configured() -> bool:
    """Captcha enforcement is on iff a known provider AND a secret are
    set. Site key is also required for the SPA to render a widget, but
    the server can verify without it — we still gate on it so the
    config-endpoint half can't drift from the verifier half."""
    provider = settings.CAPTCHA_PROVIDER
    return bool(
        provider
        and provider in _VERIFY_URLS
        and settings.CAPTCHA_SECRET_KEY
        and settings.CAPTCHA_SITE_KEY
    )


async def verify_or_raise(token: str | None, *, remote_ip: str | None) -> None:
    """Verify a captcha ``token`` against the configured provider.

    No-op when captcha isn't configured. Raises ``400 CAPTCHA_REQUIRED``
    when configured but the token is missing/blank, and
    ``400 CAPTCHA_INVALID`` when the provider rejects the token (or a
    network error prevents verification — fail-closed, since silently
    accepting on outbound provider failure would defeat the point).
    """
    if not is_configured():
        return

    cleaned = (token or "").strip()
    if not cleaned:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=AuthMessages.CAPTCHA_REQUIRED,
        )

    provider = settings.CAPTCHA_PROVIDER
    # ``is_configured`` already checked this, but ``assert`` would be
    # stripped under ``python -O`` (some production images run that
    # way). Re-check explicitly so a config that drifts between the
    # two reads doesn't surface as a 500 from a ``KeyError`` lookup.
    if provider is None or provider not in _VERIFY_URLS:
        return
    verify_url = _VERIFY_URLS[provider]

    payload: dict[str, str] = {
        "secret": settings.CAPTCHA_SECRET_KEY or "",
        "response": cleaned,
    }
    if remote_ip:
        payload["remoteip"] = remote_ip

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(verify_url, data=payload)
            resp.raise_for_status()
            body = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        # Fail-closed — if we can't reach the provider, treat as
        # invalid rather than letting a registration through unchecked.
        logger.warning(
            "Captcha verification request to %s failed: %s", provider, exc
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=AuthMessages.CAPTCHA_INVALID,
        ) from exc

    if not isinstance(body, dict) or not body.get("success"):
        # Provider error codes (if present) are intentionally not
        # forwarded to the client — they're vendor-specific and not
        # actionable for the end user. Log them for ops debugging.
        if isinstance(body, dict):
            logger.info(
                "Captcha rejected by %s: error_codes=%s",
                provider,
                body.get("error-codes") or body.get("errorCodes"),
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=AuthMessages.CAPTCHA_INVALID,
        )
