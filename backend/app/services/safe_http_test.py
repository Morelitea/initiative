"""Unit tests for guarded outbound egress.

The key property: a request is aimed at the address that was validated,
not the hostname — so the resolution used to check the target and the
resolution used to connect cannot differ.
"""

from __future__ import annotations

from unittest.mock import patch

import httpx
import pytest

from app.services.safe_http import build_validated_request, request_public_target
from app.services.webhook_target_url import (
    WebhookTargetUrlError,
    WebhookTargetUrlPrivateError,
)


def _resolves_to(ip: str):
    """Patch DNS so any hostname resolves to a single ``ip``."""
    infos = [(2, 0, 0, "", (ip, 0))]  # AF_INET
    return patch(
        "app.services.webhook_target_url.socket.getaddrinfo", return_value=infos
    )


@pytest.mark.unit
async def test_request_targets_validated_ip_and_keeps_hostname():
    with _resolves_to("93.184.216.34"):
        request = await build_validated_request(
            "POST",
            "https://hooks.example.com/deliver?x=1",
            headers={"Content-Type": "application/json"},
            content=b"{}",
        )
    # Connection target is the resolved address, not the hostname.
    assert request.url.host == "93.184.216.34"
    # Path and query are preserved.
    assert request.url.raw_path == b"/deliver?x=1"
    # Hostname is preserved for the Host header and TLS.
    assert request.headers["host"] == "hooks.example.com"
    assert request.extensions["sni_hostname"] == "hooks.example.com"


@pytest.mark.unit
async def test_host_header_includes_explicit_port():
    with _resolves_to("93.184.216.34"):
        request = await build_validated_request(
            "POST", "https://hooks.example.com:8443/x", content=b""
        )
    assert request.url.host == "93.184.216.34"
    assert request.url.port == 8443
    assert request.headers["host"] == "hooks.example.com:8443"


@pytest.mark.unit
async def test_private_resolution_is_refused():
    with _resolves_to("10.0.0.5"):
        with pytest.raises(WebhookTargetUrlPrivateError):
            await build_validated_request(
                "POST", "https://internal.example.com/x", content=b""
            )


@pytest.mark.unit
async def test_send_connects_to_pinned_ip():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["host"] = request.url.host
        seen["host_header"] = request.headers.get("host")
        seen["sni"] = request.extensions.get("sni_hostname")
        return httpx.Response(200, json={"ok": True})

    with _resolves_to("93.184.216.34"):
        response = await request_public_target(
            "POST",
            "https://hooks.example.com/deliver",
            headers={"Content-Type": "application/json"},
            content=b"{}",
            timeout=5.0,
            transport=httpx.MockTransport(handler),
        )

    assert response.status_code == 200
    assert seen == {
        "host": "93.184.216.34",
        "host_header": "hooks.example.com",
        "sni": "hooks.example.com",
    }


@pytest.mark.unit
async def test_redirects_are_not_followed():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.host)
        return httpx.Response(
            302, headers={"Location": "https://elsewhere.example.com/"}
        )

    with _resolves_to("93.184.216.34"):
        response = await request_public_target(
            "GET",
            "https://hooks.example.com/deliver",
            timeout=5.0,
            transport=httpx.MockTransport(handler),
        )

    assert response.status_code == 302
    assert calls == ["93.184.216.34"]  # only the pinned host was contacted


@pytest.mark.unit
async def test_dev_flag_pins_private_local_target(monkeypatch):
    """With the dev flag on, a local target is allowed *and* still pinned
    to the resolved address — the round-trip works and pinning holds."""
    from app.core import config as config_module

    monkeypatch.setattr(config_module.settings, "WEBHOOK_ALLOW_PRIVATE_TARGETS", True)

    with _resolves_to("127.0.0.1"):
        request = await build_validated_request(
            "POST", "http://localhost:8201/api/v1/webhooks/initiative", content=b"{}"
        )
    assert request.url.host == "127.0.0.1"
    assert request.url.scheme == "http"
    assert request.headers["host"] == "localhost:8201"


@pytest.mark.unit
async def test_falls_back_to_next_validated_address():
    """If the first validated address is unreachable, the request retries
    the other validated addresses instead of failing outright."""
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.host)
        if request.url.host == "93.184.216.34":
            raise httpx.ConnectError("refused", request=request)
        return httpx.Response(200, json={"ok": True})

    infos = [
        (2, 0, 0, "", ("93.184.216.34", 0)),
        (2, 0, 0, "", ("93.184.216.35", 0)),
    ]
    with patch(
        "app.services.webhook_target_url.socket.getaddrinfo", return_value=infos
    ):
        response = await request_public_target(
            "POST",
            "https://cdn.example.com/deliver",
            content=b"{}",
            timeout=5.0,
            transport=httpx.MockTransport(handler),
        )

    assert response.status_code == 200
    assert seen == ["93.184.216.34", "93.184.216.35"]


@pytest.mark.unit
async def test_connect_timeout_does_not_fall_back():
    """A connect timeout is not retried across addresses — it has already
    consumed the caller's budget — so the request fails without multiplying
    the timeout over every validated address."""
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.host)
        raise httpx.ConnectTimeout("timed out", request=request)

    infos = [
        (2, 0, 0, "", ("93.184.216.34", 0)),
        (2, 0, 0, "", ("93.184.216.35", 0)),
    ]
    with patch(
        "app.services.webhook_target_url.socket.getaddrinfo", return_value=infos
    ):
        with pytest.raises(httpx.ConnectTimeout):
            await request_public_target(
                "POST",
                "https://cdn.example.com/deliver",
                content=b"{}",
                timeout=5.0,
                transport=httpx.MockTransport(handler),
            )

    assert seen == ["93.184.216.34"]  # stopped after the timeout; no fallback


@pytest.mark.unit
async def test_allow_private_permits_and_pins_private_target():
    """allow_private lets an operator-configured internal target through,
    still pinned to the resolved address with the hostname preserved."""
    with _resolves_to("10.0.0.5"):
        request = await build_validated_request(
            "POST",
            "https://ollama.internal/api/chat",
            content=b"{}",
            allow_private=True,
        )
    assert request.url.host == "10.0.0.5"
    assert request.headers["host"] == "ollama.internal"


@pytest.mark.unit
async def test_allow_private_permits_http_to_private():
    """With allow_private an operator ``http://internal`` target is accepted
    and pinned (Ollama on a private host with no TLS)."""
    with _resolves_to("10.0.0.5"):
        request = await build_validated_request(
            "POST",
            "http://ollama.internal:11434/api/chat",
            content=b"{}",
            allow_private=True,
        )
    assert request.url.host == "10.0.0.5"
    assert request.url.scheme == "http"


@pytest.mark.unit
async def test_allow_private_still_rejects_http_to_public():
    """allow_private does not relax the http-to-public prohibition."""
    with _resolves_to("93.184.216.34"):
        with pytest.raises(WebhookTargetUrlError):
            await build_validated_request(
                "POST", "http://hooks.example.com/in", content=b"", allow_private=True
            )


@pytest.mark.unit
async def test_private_target_still_refused_without_allow_private():
    """Default (allow_private=False) still refuses a private target."""
    with _resolves_to("10.0.0.5"):
        with pytest.raises(WebhookTargetUrlPrivateError):
            await build_validated_request(
                "POST", "https://internal.example.com/x", content=b""
            )
