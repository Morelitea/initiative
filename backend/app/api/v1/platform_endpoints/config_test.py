"""Integration tests for the runtime config endpoint.

The SPA fetches /api/v1/config at boot to learn deployment-specific
settings (e.g. the optional captcha or billing portal). The endpoint is
unauthenticated, so the relevant invariants are about *what* it returns
under each operator config, not about access control.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.core.config import settings
from app.services.tenant.attachments import MAX_DOCUMENT_FILE_SIZE


@pytest.mark.integration
async def test_config_exposes_upload_cap(client: AsyncClient):
    """The SPA reads the server-enforced upload cap from config so the limit
    has a single source of truth (no mirrored frontend constant)."""
    response = await client.get("/api/v1/config")

    assert response.status_code == 200
    assert response.json()["max_upload_bytes"] == MAX_DOCUMENT_FILE_SIZE


@pytest.mark.integration
async def test_config_omits_billing_when_url_unset(client: AsyncClient, monkeypatch):
    """Self-host default: no BILLING_URL ⇒ ``billing: null`` so the SPA hides
    every tier/upgrade/manage surface (the usage panel still renders)."""
    monkeypatch.setattr(settings, "BILLING_URL", None)

    response = await client.get("/api/v1/config")

    assert response.status_code == 200
    assert response.json()["billing"] is None


@pytest.mark.integration
@pytest.mark.parametrize(
    ("case", "provider", "secret"),
    [
        ("no provider", None, "secret-key"),
        # Provider and site key but no secret is half-configured: nothing could
        # validate the tokens the widget would produce.
        ("no secret", "hcaptcha", None),
        # A typo in the provider name must not render an unknown widget.
        ("unrecognised provider", "definitely-not-real", "secret-key"),
    ],
    ids=lambda v: v if isinstance(v, str) and " " in v else "",
)
async def test_config_reports_no_captcha_unless_it_is_fully_configured(
    client: AsyncClient, monkeypatch, case: str, provider, secret
):
    """The SPA gets ``captcha: null`` and skips the widget, matching the
    verifier's own silent-disable behaviour."""
    monkeypatch.setattr(settings, "CAPTCHA_PROVIDER", provider)
    monkeypatch.setattr(settings, "CAPTCHA_SITE_KEY", "site-key")
    monkeypatch.setattr(settings, "CAPTCHA_SECRET_KEY", secret)

    response = await client.get("/api/v1/config")

    assert response.status_code == 200
    assert response.json()["captcha"] is None


@pytest.mark.integration
async def test_config_exposes_billing_url_when_set(client: AsyncClient, monkeypatch):
    """With a URL configured, the SPA gets the base URL to build its
    link-out buttons. The operator route reports itself unavailable until its
    own signing material is configured."""
    monkeypatch.setattr(settings, "BILLING_URL", "https://billing.example.com")
    monkeypatch.setattr(settings, "BILLING_SUPPORT_HANDOFF_SECRET", None)
    monkeypatch.setattr(settings, "BILLING_SUPPORT_HANDOFF_KID", None)

    response = await client.get("/api/v1/config")

    assert response.status_code == 200
    assert response.json()["billing"] == {
        "url": "https://billing.example.com",
        "operator_handoff": False,
    }


@pytest.mark.integration
async def test_config_reports_operator_handoff_when_signing_configured(
    client: AsyncClient, monkeypatch
):
    """Both halves present ⇒ the admin Guilds tab may render its control."""
    monkeypatch.setattr(settings, "BILLING_URL", "https://billing.example.com")
    monkeypatch.setattr(settings, "BILLING_SUPPORT_HANDOFF_SECRET", "shared-secret")
    monkeypatch.setattr(settings, "BILLING_SUPPORT_HANDOFF_KID", "k1")

    response = await client.get("/api/v1/config")

    assert response.status_code == 200
    assert response.json()["billing"]["operator_handoff"] is True


@pytest.mark.integration
async def test_config_endpoint_is_unauthenticated(client: AsyncClient):
    """The SPA needs to read this before any user is logged in. No
    cookie, no Authorization header — must still return 200."""
    # No auth headers, no cookies
    response = await client.get("/api/v1/config")

    assert response.status_code == 200


# --- Captcha exposure -----------------------------------------------------


@pytest.mark.integration
@pytest.mark.parametrize("provider", ["hcaptcha", "turnstile", "recaptcha"])
async def test_config_captcha_exposes_provider_and_site_key(
    client: AsyncClient, monkeypatch, provider: str
):
    """All three supported providers round-trip through the config
    endpoint with their public site key. The secret key never appears
    in the response."""
    monkeypatch.setattr(settings, "CAPTCHA_PROVIDER", provider)
    monkeypatch.setattr(settings, "CAPTCHA_SITE_KEY", "public-site-key")
    monkeypatch.setattr(settings, "CAPTCHA_SECRET_KEY", "very-private-secret")

    response = await client.get("/api/v1/config")

    assert response.status_code == 200
    body = response.json()
    assert body["captcha"] == {"provider": provider, "site_key": "public-site-key"}
    # Belt-and-braces: the secret must never appear in the public payload.
    assert "very-private-secret" not in response.text
