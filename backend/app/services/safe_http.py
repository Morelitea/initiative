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


class ResponseTooLargeError(Exception):
    """The response body, decoded, ran past the caller's ``max_bytes``."""


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
    allow_private: bool = False,
) -> httpx.Request:
    """Resolve and validate ``url``, then build a request whose connection
    target is the validated address, keeping the hostname for TLS SNI,
    certificate verification, and the ``Host`` header. ``allow_private``
    permits private/loopback targets (still pinned) for operator-configured
    destinations.

    Raises :class:`~app.services.webhook_target_url.WebhookTargetUrlError`
    or :class:`~app.services.webhook_target_url.WebhookTargetUrlPrivateError`
    for a disallowed target.
    """
    original = httpx.URL(url)
    target = await resolve_validated_target_async(url, allow_private=allow_private)
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
    allow_private: bool = False,
    max_bytes: int | None = None,
) -> httpx.Response:
    """Send a request to a validated public target. The host is resolved
    once; the request connects to a validated address and, if one fails
    fast (connection refused / unreachable), falls back to the other
    validated addresses. A connect *timeout* is not retried — it has
    already consumed the caller's budget — so total wall time stays bounded
    by ``timeout``. ``allow_private`` permits private/loopback targets (still
    pinned) for operator-configured destinations. ``transport`` is injectable
    for tests.

    ``max_bytes`` bounds the body as it is read, counted after any content
    decoding, and raises :class:`ResponseTooLargeError` past it. Unset, the
    body is read whole."""
    original = httpx.URL(url)
    target = await resolve_validated_target_async(url, allow_private=allow_private)
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
                response = await client.send(request, stream=max_bytes is not None)
            except httpx.ConnectError as exc:
                # Fast failure for this validated address; try the next one.
                last_exc = exc
                continue
            if max_bytes is None:
                return response
            return await _read_bounded(response, max_bytes)
    if last_exc is not None:
        raise last_exc
    # Unreachable: resolve_validated_target_async guarantees at least one
    # address, so the loop always sets last_exc on total failure.
    raise RuntimeError(f"no validated address to connect to for {url!r}")


async def _read_bounded(response: httpx.Response, max_bytes: int) -> httpx.Response:
    """A streamed response read into memory up to ``max_bytes`` decoded bytes.

    Returned as a plain response holding the decoded body, so the encoding
    headers that described the wire form are dropped with it.
    """
    body = bytearray()
    try:
        async for chunk in response.aiter_bytes():
            body += chunk
            if len(body) > max_bytes:
                raise ResponseTooLargeError(max_bytes)
    finally:
        await response.aclose()
    headers = [
        (name, value)
        for name, value in response.headers.multi_items()
        if name.lower()
        not in ("content-encoding", "content-length", "transfer-encoding")
    ]
    return httpx.Response(
        response.status_code,
        headers=headers,
        content=bytes(body),
        request=response.request,
    )
