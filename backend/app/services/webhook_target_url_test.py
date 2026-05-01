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
)


@pytest.mark.unit
def test_accepts_public_https_literal():
    """An IPv4 literal in public unicast space is fine."""
    assert_target_url_is_public("https://93.184.216.34/hook")  # example.com


@pytest.mark.unit
@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/hook",
        "http://127.255.255.254/hook",
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
        "http://10.0.0.1/hook",
        "http://172.16.0.1/hook",
        "http://192.168.1.1/hook",
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
        assert_target_url_is_public("http://169.254.169.254/latest/meta-data/")


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
    """Only http(s) — anything else (file, ftp, gopher, javascript) is
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
