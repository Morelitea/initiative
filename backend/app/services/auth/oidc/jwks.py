"""Resolve an OIDC provider's signing key from its JWKS.

Given a trusted ``jwks_uri`` and a raw token, fetch the provider's JSON Web Key
Set and return the ``PyJWK`` whose ``kid`` matches the token header, for the
verifier (:mod:`app.services.auth.oidc.id_token`) to check the signature against.

Fetched with httpx (async) rather than PyJWT's blocking ``PyJWKClient``, so the
request is controlled directly:

* the ``jwks_uri`` must be ``https`` (rejected before any request otherwise);
* the response body is read under a fixed size cap;
* the key set is cached (TTL); an unknown ``kid`` triggers at most one refetch
  per interval.

Parsing uses PyJWT (``PyJWKSet``); the fetch does not. Any failure raises
:class:`JwksResolutionError` — fail-closed, so an unresolved key blocks login.
See the auth design doc for the rationale.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx
import jwt

DEFAULT_CACHE_TTL_SECONDS: float = 300.0
DEFAULT_MIN_REFETCH_INTERVAL_SECONDS: float = 10.0
DEFAULT_HTTP_TIMEOUT_SECONDS: float = 10.0
# A JWKS is a few KiB; 512 KiB is generous headroom.
DEFAULT_MAX_RESPONSE_BYTES: int = 512 * 1024

ClientFactory = Callable[[], httpx.AsyncClient]


class JwksResolutionError(Exception):
    """The provider's signing key could not be resolved; verification must not
    proceed (fail-closed)."""


@dataclass
class _CachedKeySet:
    key_set: jwt.PyJWKSet
    fetched_at: float  # monotonic clock


class JwksResolver:
    """Fetches + caches provider JWKS and resolves a token's signing key.

    Hold one instance per process (the cache is shared across requests). The
    network client is built per fetch via ``client_factory`` so tests can inject
    an ``httpx.MockTransport`` without patching globals.
    """

    def __init__(
        self,
        *,
        cache_ttl_seconds: float = DEFAULT_CACHE_TTL_SECONDS,
        min_refetch_interval_seconds: float = DEFAULT_MIN_REFETCH_INTERVAL_SECONDS,
        http_timeout_seconds: float = DEFAULT_HTTP_TIMEOUT_SECONDS,
        max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
        client_factory: ClientFactory | None = None,
    ) -> None:
        self._cache_ttl = cache_ttl_seconds
        self._min_refetch_interval = min_refetch_interval_seconds
        self._timeout = http_timeout_seconds
        self._max_bytes = max_response_bytes
        self._client_factory = client_factory or self._default_client_factory
        self._cache: dict[str, _CachedKeySet] = {}

    def _default_client_factory(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=self._timeout)

    async def resolve_signing_key(self, raw_token: str, *, jwks_uri: str) -> jwt.PyJWK:
        """Return the ``PyJWK`` for ``raw_token``'s ``kid`` from the JWKS at
        ``jwks_uri`` (fetching/caching as needed), or raise
        :class:`JwksResolutionError`.

        The ``kid`` is read from the token's *unverified* header — it only
        selects which key to check against; authenticity comes from the
        signature check, not the header.
        """
        try:
            header = jwt.get_unverified_header(raw_token)
        except jwt.PyJWTError as exc:
            raise JwksResolutionError(f"unreadable token header: {exc}") from exc
        kid = header.get("kid")

        key_set = await self._get_key_set(jwks_uri)
        key = _select_key(key_set, kid)
        if key is None and self._may_refetch(jwks_uri):
            # kid absent from the cached set — keys may have rotated. One
            # rate-limited refetch, then give up (bounds outbound fetches).
            key_set = await self._fetch_and_cache(jwks_uri)
            key = _select_key(key_set, kid)
        if key is None:
            raise JwksResolutionError(
                f"no signing key for kid={kid!r} in JWKS at {jwks_uri}"
            )
        return key

    async def _get_key_set(self, jwks_uri: str) -> jwt.PyJWKSet:
        cached = self._cache.get(jwks_uri)
        if cached is not None:
            if (time.monotonic() - cached.fetched_at) < self._cache_ttl:
                return cached.key_set
        return await self._fetch_and_cache(jwks_uri)

    def _may_refetch(self, jwks_uri: str) -> bool:
        cached = self._cache.get(jwks_uri)
        if cached is None:
            return True
        return (time.monotonic() - cached.fetched_at) >= self._min_refetch_interval

    async def _fetch_and_cache(self, jwks_uri: str) -> jwt.PyJWKSet:
        key_set = await self._fetch(jwks_uri)
        self._cache[jwks_uri] = _CachedKeySet(
            key_set=key_set, fetched_at=time.monotonic()
        )
        return key_set

    async def _fetch(self, jwks_uri: str) -> jwt.PyJWKSet:
        _require_https(jwks_uri)
        try:
            async with self._client_factory() as client:
                async with client.stream("GET", jwks_uri) as resp:
                    resp.raise_for_status()
                    body = bytearray()
                    async for chunk in resp.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > self._max_bytes:
                            raise JwksResolutionError(
                                f"JWKS at {jwks_uri} exceeds the "
                                f"{self._max_bytes}-byte cap"
                            )
        except httpx.HTTPError as exc:
            raise JwksResolutionError(
                f"JWKS fetch failed for {jwks_uri}: {exc}"
            ) from exc
        try:
            return jwt.PyJWKSet.from_dict(json.loads(body))
        except (ValueError, jwt.PyJWTError) as exc:
            raise JwksResolutionError(f"invalid JWKS at {jwks_uri}: {exc}") from exc


def _require_https(jwks_uri: str) -> None:
    # urlsplit lowercases the scheme, so ``HTTP`` etc. are covered; a missing host
    # (``https://``) is refused too.
    parts = urlsplit(jwks_uri)
    if parts.scheme != "https" or not parts.netloc:
        raise JwksResolutionError(f"refusing non-https JWKS URI: {jwks_uri!r}")


def _select_key(key_set: jwt.PyJWKSet, kid: str | None) -> jwt.PyJWK | None:
    keys = key_set.keys
    if kid is not None:
        return next((k for k in keys if k.key_id == kid), None)
    # No kid in the token: only unambiguous when the set has exactly one key.
    return keys[0] if len(keys) == 1 else None
