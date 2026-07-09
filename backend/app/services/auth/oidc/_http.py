"""Shared HTTPS JSON requests for the OIDC client (discovery, JWKS, token
endpoint).

One place for the network hardening every OIDC call needs — https-only, a fixed
response size cap, a timeout — so it is written and audited once rather than
copied. Callers add their own caching and wrap :class:`OidcHttpError` in a
domain-specific error.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit

import httpx

ClientFactory = Callable[[], httpx.AsyncClient]

DEFAULT_HTTP_TIMEOUT_SECONDS: float = 10.0
# A discovery doc / JWKS is a few KiB; 512 KiB is generous headroom.
DEFAULT_MAX_RESPONSE_BYTES: int = 512 * 1024
# Error bodies are logged, so keep only enough for the diagnostic payload.
_ERROR_SNIPPET_MAX_BYTES: int = 2048


class OidcHttpError(Exception):
    """An OIDC HTTPS fetch failed — non-https URL, transport/status error,
    oversized body, or invalid JSON. Callers wrap it in their own error."""


def require_https(url: str) -> None:
    # urlsplit lowercases the scheme, so ``HTTP`` etc. are covered; a missing host
    # (``https://``) is refused too.
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.netloc:
        raise OidcHttpError(f"refusing non-https URL: {url!r}")


async def fetch_json(
    url: str,
    *,
    client_factory: ClientFactory | None = None,
    timeout_seconds: float = DEFAULT_HTTP_TIMEOUT_SECONDS,
    max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
) -> Any:
    """GET ``url`` and return its parsed JSON, enforcing https and a response
    size cap. Raises :class:`OidcHttpError` on any failure (fail-closed).

    ``client_factory`` builds the ``httpx.AsyncClient`` per call (tests inject a
    ``MockTransport``); it defaults to a timeout-configured client.
    """
    return await _request_json(
        "GET",
        url,
        client_factory=client_factory,
        timeout_seconds=timeout_seconds,
        max_response_bytes=max_response_bytes,
    )


async def post_form_json(
    url: str,
    data: dict[str, str],
    *,
    client_factory: ClientFactory | None = None,
    timeout_seconds: float = DEFAULT_HTTP_TIMEOUT_SECONDS,
    max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
) -> Any:
    """POST ``data`` as a form to ``url`` and return the parsed JSON response,
    with the same https / size-cap / fail-closed contract as :func:`fetch_json`.
    Used for the token-endpoint exchange."""
    return await _request_json(
        "POST",
        url,
        data=data,
        client_factory=client_factory,
        timeout_seconds=timeout_seconds,
        max_response_bytes=max_response_bytes,
    )


async def _request_json(
    method: str,
    url: str,
    *,
    data: dict[str, str] | None = None,
    client_factory: ClientFactory | None,
    timeout_seconds: float,
    max_response_bytes: int,
) -> Any:
    require_https(url)
    factory = client_factory or (lambda: httpx.AsyncClient(timeout=timeout_seconds))
    body = bytearray()
    # Failures are flagged and raised AFTER the stream context exits: raising
    # inside it would leave our exception exposed to replacement by a teardown
    # error from the abandoned body (the transport may fault when we stop
    # reading mid-stream).
    over_cap = False
    error_status: int | None = None
    try:
        async with factory() as client:
            async with client.stream(method, url, data=data) as resp:
                if resp.status_code >= 400:
                    # Read a bounded snippet of the error body: an OAuth error
                    # response ({"error": "invalid_grant", ...}) is the one
                    # diagnostic the server operator needs in the logs.
                    error_status = resp.status_code
                    max_bytes = _ERROR_SNIPPET_MAX_BYTES
                else:
                    max_bytes = max_response_bytes
                async for chunk in resp.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > max_bytes:
                        over_cap = True
                        break
    except httpx.HTTPError as exc:
        raise OidcHttpError(f"fetch failed for {url}: {exc}") from exc
    if error_status is not None:
        snippet = body[:_ERROR_SNIPPET_MAX_BYTES].decode("utf-8", errors="replace")
        raise OidcHttpError(f"{url} returned {error_status}: {snippet}")
    if over_cap:
        raise OidcHttpError(
            f"response from {url} exceeds the {max_response_bytes}-byte cap"
        )
    try:
        return json.loads(body)
    except ValueError as exc:
        raise OidcHttpError(f"invalid JSON from {url}: {exc}") from exc
