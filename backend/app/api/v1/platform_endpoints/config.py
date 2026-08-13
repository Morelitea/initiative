"""Runtime configuration endpoint.

The SPA fetches this on boot to learn deployment-specific settings that
can't be baked into the static build (Vite vars are compile-time). The
response is intentionally narrow — only public-safe values that affect
UI surfacing.

Unauthenticated: the SPA needs this before any user is logged in.
"""

from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel

from app.core.config import settings
from app.core.security import billing_support_handoff_enabled
from app.services.tenant.attachments import MAX_DOCUMENT_FILE_SIZE

router = APIRouter()


class CaptchaConfig(BaseModel):
    """Public-safe captcha settings the SPA needs to render a widget.

    Only the provider name and the (public) site key are exposed —
    the secret key stays server-side. ``None`` (i.e. the surrounding
    ``AppConfig.captcha`` field is null) means the deployment has no
    captcha configured and the SPA shouldn't render a widget at all.
    Mirrors the silent-disable behaviour of the verifier in
    ``app.services.captcha``.
    """

    provider: str  # "hcaptcha" | "turnstile" | "recaptcha"
    site_key: str


class BillingConfig(BaseModel):
    """Public link-out to an external billing portal.

    When ``BILLING_URL`` is unset on the backend (the default) this whole
    field is ``None`` and the SPA shows no tier label, upgrade, or
    manage-billing UI. The usage panel (caps + usage, all operator-set
    numbers) renders regardless. Only the base URL crosses.
    """

    url: str
    # Whether the operator route into the portal is wired up. The admin Guilds
    # tab hides its billing control when false rather than offering one whose
    # every click fails. Independent of ``url`` — the guild-admin link-out
    # works without it.
    operator_handoff: bool = False


class AppConfig(BaseModel):
    """Public, runtime-injected configuration consumed by the SPA at boot."""

    captcha: Optional[CaptchaConfig] = None
    billing: Optional[BillingConfig] = None
    # The upload size cap the server enforces on file endpoints. The SPA reads
    # it for pre-flight checks so the number lives in exactly one place.
    max_upload_bytes: int


_SUPPORTED_CAPTCHA_PROVIDERS = {"hcaptcha", "turnstile", "recaptcha"}


@router.get("/config", response_model=AppConfig)
def get_app_config() -> AppConfig:
    # Captcha: only expose when all three of provider / site key / secret
    # are present and the provider name is one we recognise. The SPA
    # treats a missing ``captcha`` field as "no captcha for this
    # deployment" and skips the widget. Mirrors the verifier's
    # ``is_configured`` predicate in ``app.services.captcha``.
    captcha: Optional[CaptchaConfig] = None
    provider = settings.CAPTCHA_PROVIDER
    if (
        provider
        and provider in _SUPPORTED_CAPTCHA_PROVIDERS
        and settings.CAPTCHA_SITE_KEY
        and settings.CAPTCHA_SECRET_KEY
    ):
        captcha = CaptchaConfig(provider=provider, site_key=settings.CAPTCHA_SITE_KEY)

    # Billing portal link-out: exposed only when the operator configured a
    # billing URL. Absent ⇒ the SPA hides every tier/upgrade/manage surface.
    billing = (
        BillingConfig(
            url=settings.BILLING_URL,
            operator_handoff=billing_support_handoff_enabled(),
        )
        if settings.BILLING_URL
        else None
    )

    return AppConfig(
        captcha=captcha,
        billing=billing,
        max_upload_bytes=MAX_DOCUMENT_FILE_SIZE,
    )
