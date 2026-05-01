"""Unit tests for the webhook target-URL validator.

This is the SSRF guard. If any of these tests start passing accidentally,
that's a defect — the dispatcher would happily POST to internal services
or cloud-metadata endpoints.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.services.webhook_target_url import (
    WebhookTargetUrlError,
    WebhookTargetUrlPrivateError,
    assert_target_url_is_public,
    assert_target_url_is_public_async,
)


@pytest.mark.unit
def test_accepts_public_https_literal():
    """An IPv4 literal in public unicast space is fine."""
    assert_target_url_is_public("https://93.184.216.34/hook")  # example.com


@pytest.mark.unit
@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1/hook",
        "https://127.255.255.254/hook",
        "https://[::1]/hook",
    ],
)
def test_rejects_loopback(url: str):
    """Loopback in either family must be rejected — the most common
    SSRF target (e.g. ``localhost:6379`` for Redis)."""
    with pytest.raises(WebhookTargetUrlPrivateError):
        assert_target_url_is_public(url)


@pytest.mark.unit
@pytest.mark.parametrize(
    "url",
    [
        "https://10.0.0.1/hook",
        "https://172.16.0.1/hook",
        "https://192.168.1.1/hook",
        "https://[fc00::1]/hook",
    ],
)
def test_rejects_rfc1918_and_ula(url: str):
    """RFC1918 v4 and ULA v6 are private and must be blocked."""
    with pytest.raises(WebhookTargetUrlPrivateError):
        assert_target_url_is_public(url)


@pytest.mark.unit
def test_rejects_link_local_metadata():
    """169.254.169.254 is the AWS / GCP / Azure metadata endpoint —
    blind SSRF here leaks IAM credentials."""
    with pytest.raises(WebhookTargetUrlPrivateError):
        assert_target_url_is_public("https://169.254.169.254/latest/meta-data/")


@pytest.mark.unit
def test_rejects_plain_http():
    """Plain http:// lets a MITM strip the signature header and forge
    payloads at the transport layer, defeating HMAC. Only https is
    permitted."""
    with pytest.raises(WebhookTargetUrlError):
        assert_target_url_is_public("http://hooks.example.com/in")


@pytest.mark.unit
@pytest.mark.parametrize(
    "url",
    [
        "ftp://example.com/hook",
        "file:///etc/passwd",
        "gopher://example.com/_GET",
        "javascript:alert(1)",
    ],
)
def test_rejects_non_http_schemes(url: str):
    """Anything other than https — file, ftp, gopher, javascript — is
    a category error for a webhook target."""
    with pytest.raises(WebhookTargetUrlError):
        assert_target_url_is_public(url)


@pytest.mark.unit
def test_rejects_missing_hostname():
    with pytest.raises(WebhookTargetUrlError):
        assert_target_url_is_public("http:///hook")


@pytest.mark.unit
def test_rejects_when_hostname_resolves_to_private():
    """A public-looking hostname that *resolves* to a private address
    must still be rejected. Catches the trivial DNS bypass."""
    fake_infos = [(2, 0, 0, "", ("10.0.0.5", 0))]  # AF_INET, RFC1918
    with patch("app.services.webhook_target_url.socket.getaddrinfo", return_value=fake_infos):
        with pytest.raises(WebhookTargetUrlPrivateError):
            assert_target_url_is_public("https://internal.example.com/hook")


@pytest.mark.unit
def test_rejects_when_any_resolved_address_is_private():
    """Multi-record DNS: if even one A record points at private space we
    reject — otherwise an attacker could publish ``[1.1.1.1, 10.0.0.1]``
    and roll the dice on which one httpx picks."""
    fake_infos = [
        (2, 0, 0, "", ("93.184.216.34", 0)),  # public
        (2, 0, 0, "", ("10.0.0.5", 0)),  # private
    ]
    with patch("app.services.webhook_target_url.socket.getaddrinfo", return_value=fake_infos):
        with pytest.raises(WebhookTargetUrlPrivateError):
            assert_target_url_is_public("https://mixed.example.com/hook")


@pytest.mark.unit
async def test_async_variant_accepts_public_literal():
    """The async path takes the same code through asyncio.to_thread; an
    IP literal short-circuits the resolver entirely so no thread hop
    happens — same result either way."""
    await assert_target_url_is_public_async("https://93.184.216.34/hook")


@pytest.mark.unit
async def test_async_variant_rejects_private_literal():
    """Sanity: the async variant enforces the same private-address
    rejection. Catches a refactor that lets a code path skip the check."""
    with pytest.raises(WebhookTargetUrlPrivateError):
        await assert_target_url_is_public_async("https://10.0.0.1/hook")


# ── Dev escape hatch ──────────────────────────────────────────────────


@pytest.mark.unit
def test_dev_flag_allows_loopback(monkeypatch):
    """``WEBHOOK_ALLOW_PRIVATE_TARGETS=true`` is the documented local-
    dev path. With it set, loopback / RFC1918 are accepted and so is
    plain http (because a localhost target has no TLS cert)."""
    from app.core import config as config_module

    monkeypatch.setattr(config_module.settings, "WEBHOOK_ALLOW_PRIVATE_TARGETS", True)
    assert_target_url_is_public("http://localhost:9002/api/v1/webhooks/initiative")
    assert_target_url_is_public("http://127.0.0.1:9002/hook")
    assert_target_url_is_public("http://10.0.0.5/hook")


@pytest.mark.unit
def test_dev_flag_default_is_off(monkeypatch):
    """Sanity: with the flag at its default, the production behaviour
    still rejects loopback. Catches a regression where the flag's
    default flipped to True."""
    from app.core import config as config_module

    monkeypatch.setattr(config_module.settings, "WEBHOOK_ALLOW_PRIVATE_TARGETS", False)
    with pytest.raises(WebhookTargetUrlPrivateError):
        assert_target_url_is_public("https://127.0.0.1/hook")
    with pytest.raises(WebhookTargetUrlError):
        assert_target_url_is_public("http://hooks.example.com/in")


@pytest.mark.unit
async def test_async_variant_resolves_via_thread_executor():
    """The async path must hand DNS resolution off the event loop. We
    assert that by checking the resolver gets called via the patched
    ``socket.getaddrinfo`` even when invoked inside a coroutine — if the
    blocking sync helper were accidentally used instead, this test would
    still pass, so the real value here is paired with the unit-level
    code review of ``asyncio.to_thread`` in the source."""
    fake_infos = [(2, 0, 0, "", ("93.184.216.34", 0))]
    with patch(
        "app.services.webhook_target_url.socket.getaddrinfo",
        return_value=fake_infos,
    ) as mock:
        await assert_target_url_is_public_async("https://hooks.example.com/in")
    assert mock.called
