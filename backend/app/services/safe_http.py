"""Central egress helper for outbound HTTP to caller-influenced URLs.

Webhook delivery and the custom AI provider both send requests to URLs a
guild member can set. Both go through :func:`request_public_target` so
the target policy (see :mod:`app.services.webhook_target_url`) is enforced
in one place and the request connects to the address that was validated.

The host is resolved once; the request is aimed at the resulting address
while the original hostname is preserved for TLS SNI, certificate
verification, and the ``Host`` header. Redirects are not followed.
"""

from __future__ import annotations

from typing import Any

import httpx

from app.services.webhook_target_url import resolve_validated_target_async


def _authority(url: httpx.URL) -> str:
    """``host[:port]`` for the ``Host`` header, bracketing IPv6 literals
    and including the port only when the URL specified one."""
    host = url.host
    bracketed = f"[{host}]" if ":" in host else host
    port = url.port
    return f"{bracketed}:{port}" if port is not None else bracketed


async def build_validated_request(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    content: bytes | None = None,
    json: Any = None,
) -> httpx.Request:
    """Resolve and validate ``url``, then build a request whose connection
    target is the validated address, keeping the hostname for TLS SNI,
    certificate verification, and the ``Host`` header.

    Raises :class:`~app.services.webhook_target_url.WebhookTargetUrlError`
    or :class:`~app.services.webhook_target_url.WebhookTargetUrlPrivateError`
    for a disallowed target.
    """
    original = httpx.URL(url)
    target = await resolve_validated_target_async(url)
    pinned_url = original.copy_with(host=target.pinned_ip)
    merged = dict(headers or {})
    merged["Host"] = _authority(original)
    return httpx.Request(
        method,
        pinned_url,
        headers=merged,
        content=content,
        json=json,
        extensions={"sni_hostname": target.hostname},
    )


async def request_public_target(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    content: bytes | None = None,
    json: Any = None,
    timeout: httpx.Timeout | float,
    transport: httpx.AsyncBaseTransport | None = None,
) -> httpx.Response:
    """Send a request to a validated public target, connected to the
    address that was checked. ``transport`` is injectable for tests."""
    request = await build_validated_request(
        method, url, headers=headers, content=content, json=json
    )
    async with httpx.AsyncClient(
        timeout=timeout, follow_redirects=False, transport=transport
    ) as client:
        return await client.send(request)
