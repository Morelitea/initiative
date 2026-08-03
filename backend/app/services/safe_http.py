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
    return _pin_request(
        method,
        original,
        target.pinned_ip,
        target.hostname,
        headers=headers,
        content=content,
        json=json,
    )


def _pin_request(
    method: str,
    original: httpx.URL,
    ip: str,
    hostname: str,
    *,
    headers: dict[str, str] | None,
    content: bytes | None,
    json: Any,
) -> httpx.Request:
    """Build a request aimed at ``ip`` while keeping ``hostname`` for TLS
    SNI, certificate verification, and the ``Host`` header."""
    merged = dict(headers or {})
    merged["Host"] = _authority(original)
    return httpx.Request(
        method,
        original.copy_with(host=ip),
        headers=merged,
        content=content,
        json=json,
        extensions={"sni_hostname": hostname},
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
    """Send a request to a validated public target. The host is resolved
    once; the request connects to a validated address and, if one fails
    fast (connection refused / unreachable), falls back to the other
    validated addresses. A connect *timeout* is not retried — it has
    already consumed the caller's budget — so total wall time stays bounded
    by ``timeout``. ``transport`` is injectable for tests."""
    original = httpx.URL(url)
    target = await resolve_validated_target_async(url)
    last_exc: httpx.ConnectError | None = None
    async with httpx.AsyncClient(
        timeout=timeout, follow_redirects=False, transport=transport
    ) as client:
        for address in target.addresses:
            request = _pin_request(
                method,
                original,
                str(address),
                target.hostname,
                headers=headers,
                content=content,
                json=json,
            )
            try:
                return await client.send(request)
            except httpx.ConnectError as exc:
                # Fast failure for this validated address; try the next one.
                last_exc = exc
    if last_exc is not None:
        raise last_exc
    # Unreachable: resolve_validated_target_async guarantees at least one
    # address, so the loop always sets last_exc on total failure.
    raise RuntimeError(f"no validated address to connect to for {url!r}")
