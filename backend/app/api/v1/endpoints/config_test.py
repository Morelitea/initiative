"""Integration tests for the runtime config endpoint.

The SPA fetches /api/v1/config at boot to learn deployment-specific
settings (e.g. the optional advanced-tool URL). The endpoint is
unauthenticated, so the relevant invariants are about *what* it returns
under each operator config, not about access control.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.core.config import settings


@pytest.mark.integration
async def test_config_returns_no_advanced_tool_when_url_unset(
    client: AsyncClient, monkeypatch
):
    """OSS deployments leave ADVANCED_TOOL_URL unset; the SPA must see
    ``advanced_tool: null`` so it hides the toggle, sidebar entry, and
    settings tab. This is the load-bearing default."""
    monkeypatch.setattr(settings, "ADVANCED_TOOL_URL", None)
    monkeypatch.setattr(settings, "ADVANCED_TOOL_NAME", None)
    monkeypatch.setattr(settings, "ADVANCED_TOOL_ALLOWED_ORIGINS", [])
    monkeypatch.setattr(settings, "CAPTCHA_PROVIDER", None)
    monkeypatch.setattr(settings, "CAPTCHA_SITE_KEY", None)
    monkeypatch.setattr(settings, "CAPTCHA_SECRET_KEY", None)

    response = await client.get("/api/v1/config")

    assert response.status_code == 200
    assert response.json() == {"advanced_tool": None, "captcha": None}


@pytest.mark.integration
async def test_config_exposes_advanced_tool_when_url_set(
    client: AsyncClient, monkeypatch
):
    """When the URL is configured, the SPA needs name + url + the
    inbound postMessage allowlist. Without an explicit allowlist, the
    iframe URL's own origin is the only entry."""
    monkeypatch.setattr(settings, "ADVANCED_TOOL_URL", "https://embed.example.com")
    monkeypatch.setattr(settings, "ADVANCED_TOOL_NAME", "Automations")
    monkeypatch.setattr(settings, "ADVANCED_TOOL_ALLOWED_ORIGINS", [])

    response = await client.get("/api/v1/config")

    assert response.status_code == 200
    body = response.json()
    assert body["advanced_tool"] == {
        "name": "Automations",
        "url": "https://embed.example.com",
        "allowed_origins": ["https://embed.example.com"],
    }


@pytest.mark.integration
async def test_config_falls_back_to_default_name_when_unset(
    client: AsyncClient, monkeypatch
):
    """A configured URL with no name should still be usable — the SPA
    falls back to a sensible default rather than rendering an empty
    label in the tab/toggle."""
    monkeypatch.setattr(settings, "ADVANCED_TOOL_URL", "https://embed.example.com")
    monkeypatch.setattr(settings, "ADVANCED_TOOL_NAME", None)
    monkeypatch.setattr(settings, "ADVANCED_TOOL_ALLOWED_ORIGINS", [])

    response = await client.get("/api/v1/config")

    assert response.status_code == 200
    assert response.json()["advanced_tool"]["name"] == "Advanced Tool"


@pytest.mark.integration
async def test_config_extends_allowed_origins_with_operator_list(
    client: AsyncClient, monkeypatch
):
    """Operators behind a CDN with multiple origins can extend the
    allowlist via ADVANCED_TOOL_ALLOWED_ORIGINS. The iframe URL origin
    is *always* prepended so a misconfigured list can't lock the SPA
    out of its own embed."""
    monkeypatch.setattr(settings, "ADVANCED_TOOL_URL", "https://embed.example.com")
    monkeypatch.setattr(settings, "ADVANCED_TOOL_NAME", "Automations")
    monkeypatch.setattr(
        settings,
        "ADVANCED_TOOL_ALLOWED_ORIGINS",
        ["https://embed-eu.example.com", "https://embed-us.example.com"],
    )

    response = await client.get("/api/v1/config")

    assert response.status_code == 200
    assert response.json()["advanced_tool"]["allowed_origins"] == [
        "https://embed.example.com",
        "https://embed-eu.example.com",
        "https://embed-us.example.com",
    ]


@pytest.mark.integration
async def test_config_strips_default_ports_to_match_browser_origin(
    client: AsyncClient, monkeypatch
):
    """``new URL(url).origin`` in browsers strips the port if it's the
    scheme default (443 for https, 80 for http). The backend must do the
    same when computing the iframe origin, otherwise an operator who
    explicitly writes ``https://embed.example.com:443`` ends up with an
    allowlist entry that never matches the browser's normalized
    ``event.origin``. Non-default ports are preserved as-is."""
    monkeypatch.setattr(
        settings, "ADVANCED_TOOL_URL", "https://embed.example.com:443"
    )
    monkeypatch.setattr(settings, "ADVANCED_TOOL_NAME", "Automations")
    monkeypatch.setattr(settings, "ADVANCED_TOOL_ALLOWED_ORIGINS", [])

    response = await client.get("/api/v1/config")

    assert response.status_code == 200
    body = response.json()
    # Default port stripped — matches what the browser produces
    assert body["advanced_tool"]["allowed_origins"] == [
        "https://embed.example.com"
    ]


@pytest.mark.integration
async def test_config_preserves_non_default_ports(
    client: AsyncClient, monkeypatch
):
    """Non-default ports must round-trip — a localhost-with-port deploy
    (e.g. dev) breaks if the port disappears."""
    monkeypatch.setattr(settings, "ADVANCED_TOOL_URL", "http://localhost:9001")
    monkeypatch.setattr(settings, "ADVANCED_TOOL_NAME", "Automations")
    monkeypatch.setattr(settings, "ADVANCED_TOOL_ALLOWED_ORIGINS", [])

    response = await client.get("/api/v1/config")

    assert response.status_code == 200
    assert response.json()["advanced_tool"]["allowed_origins"] == [
        "http://localhost:9001"
    ]


@pytest.mark.integration
async def test_config_dedupes_iframe_origin_in_allowlist(
    client: AsyncClient, monkeypatch
):
    """If the operator includes the iframe URL's origin in the
    allowlist, it should appear once — not twice — so the SPA's
    ``Set`` lookup behaves predictably either way."""
    monkeypatch.setattr(settings, "ADVANCED_TOOL_URL", "https://embed.example.com")
    monkeypatch.setattr(settings, "ADVANCED_TOOL_NAME", "Automations")
    monkeypatch.setattr(
        settings,
        "ADVANCED_TOOL_ALLOWED_ORIGINS",
        ["https://embed.example.com", "https://other.example.com"],
    )

    response = await client.get("/api/v1/config")

    assert response.status_code == 200
    origins = response.json()["advanced_tool"]["allowed_origins"]
    assert origins == ["https://embed.example.com", "https://other.example.com"]
    assert origins.count("https://embed.example.com") == 1


@pytest.mark.integration
async def test_config_endpoint_is_unauthenticated(
    client: AsyncClient, monkeypatch
):
    """The SPA needs to read this before any user is logged in. No
    cookie, no Authorization header — must still return 200."""
    monkeypatch.setattr(settings, "ADVANCED_TOOL_URL", None)
    monkeypatch.setattr(settings, "ADVANCED_TOOL_NAME", None)
    monkeypatch.setattr(settings, "ADVANCED_TOOL_ALLOWED_ORIGINS", [])

    # No auth headers, no cookies
    response = await client.get("/api/v1/config")

    assert response.status_code == 200


# --- Captcha exposure -----------------------------------------------------


@pytest.mark.integration
async def test_config_captcha_null_when_provider_unset(
    client: AsyncClient, monkeypatch
):
    """No provider env var → SPA gets ``captcha: null`` and skips the
    widget, matching the verifier's silent-disable behaviour."""
    monkeypatch.setattr(settings, "CAPTCHA_PROVIDER", None)
    monkeypatch.setattr(settings, "CAPTCHA_SITE_KEY", "site-key")
    monkeypatch.setattr(settings, "CAPTCHA_SECRET_KEY", "secret-key")

    response = await client.get("/api/v1/config")

    assert response.status_code == 200
    assert response.json()["captcha"] is None


@pytest.mark.integration
async def test_config_captcha_null_when_secret_missing(
    client: AsyncClient, monkeypatch
):
    """Provider + site key without a secret is half-configured — the
    verifier can't actually validate tokens. Treat as disabled instead
    of pretending it works."""
    monkeypatch.setattr(settings, "CAPTCHA_PROVIDER", "hcaptcha")
    monkeypatch.setattr(settings, "CAPTCHA_SITE_KEY", "site-key")
    monkeypatch.setattr(settings, "CAPTCHA_SECRET_KEY", None)

    response = await client.get("/api/v1/config")

    assert response.status_code == 200
    assert response.json()["captcha"] is None


@pytest.mark.integration
async def test_config_captcha_null_when_provider_unrecognised(
    client: AsyncClient, monkeypatch
):
    """Typos in CAPTCHA_PROVIDER (e.g. ``"hcaptcha-v2"``) shouldn't
    silently render an unknown widget — bail out safely instead."""
    monkeypatch.setattr(settings, "CAPTCHA_PROVIDER", "definitely-not-real")
    monkeypatch.setattr(settings, "CAPTCHA_SITE_KEY", "site-key")
    monkeypatch.setattr(settings, "CAPTCHA_SECRET_KEY", "secret-key")

    response = await client.get("/api/v1/config")

    assert response.status_code == 200
    assert response.json()["captcha"] is None


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
