"""Shared HTTPS JSON fetch for the OIDC client (discovery + JWKS).

One place for the network hardening both fetchers need — https-only, a fixed
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
    require_https(url)
    factory = client_factory or (lambda: httpx.AsyncClient(timeout=timeout_seconds))
    body = bytearray()
    # The cap is flagged and raised AFTER the stream context exits: raising inside
    # it would leave our exception exposed to replacement by a teardown error from
    # the abandoned body (the transport may fault when we stop reading mid-stream).
    over_cap = False
    try:
        async with factory() as client:
            async with client.stream("GET", url) as resp:
                resp.raise_for_status()
                async for chunk in resp.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > max_response_bytes:
                        over_cap = True
                        break
    except httpx.HTTPError as exc:
        raise OidcHttpError(f"fetch failed for {url}: {exc}") from exc
    if over_cap:
        raise OidcHttpError(
            f"response from {url} exceeds the {max_response_bytes}-byte cap"
        )
    try:
        return json.loads(body)
    except ValueError as exc:
        raise OidcHttpError(f"invalid JSON from {url}: {exc}") from exc
