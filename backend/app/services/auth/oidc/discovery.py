"""OIDC provider discovery — fetch + validate ``.well-known/openid-configuration``.

Turns a configured ``issuer`` into the endpoints the relying-party flow needs
(authorization, token, JWKS). The security-relevant checks:

* the discovery document is fetched over https under a size cap (shared
  :mod:`app.services.auth.oidc._http`);
* the ``issuer`` inside the document must equal the configured issuer — a
  provider may not use its metadata to point trust at a different identity;
* ``authorization_endpoint`` / ``token_endpoint`` / ``jwks_uri`` must be present
  and https.

Cached per issuer (metadata changes rarely); any failure raises
:class:`DiscoveryError` (fail-closed).
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any

from app.services.auth.oidc._http import (
    DEFAULT_HTTP_TIMEOUT_SECONDS,
    DEFAULT_MAX_RESPONSE_BYTES,
    ClientFactory,
    OidcHttpError,
    fetch_json,
    require_https,
)

DEFAULT_CACHE_TTL_SECONDS: float = 3600.0
_WELL_KNOWN_SUFFIX = "/.well-known/openid-configuration"


class DiscoveryError(Exception):
    """Provider discovery failed; the flow cannot proceed (fail-closed)."""


@dataclass(frozen=True)
class OidcMetadata:
    """The subset of discovery metadata the relying-party flow uses."""

    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    jwks_uri: str
    # Advertised id_token signing algs, if the provider lists them — lets the
    # caller narrow the verifier's allowlist to what this provider actually uses.
    id_token_signing_alg_values_supported: tuple[str, ...] | None = None


@dataclass
class _CachedMetadata:
    metadata: OidcMetadata
    fetched_at: float  # monotonic clock


class OidcDiscovery:
    """Fetches + caches provider discovery metadata.

    Hold one instance per process (the cache is shared). The network client is
    built per fetch via ``client_factory`` so tests can inject a
    ``httpx.MockTransport`` without patching globals.
    """

    def __init__(
        self,
        *,
        cache_ttl_seconds: float = DEFAULT_CACHE_TTL_SECONDS,
        http_timeout_seconds: float = DEFAULT_HTTP_TIMEOUT_SECONDS,
        max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
        client_factory: ClientFactory | None = None,
    ) -> None:
        self._cache_ttl = cache_ttl_seconds
        self._timeout = http_timeout_seconds
        self._max_bytes = max_response_bytes
        self._client_factory = client_factory
        self._cache: dict[str, _CachedMetadata] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    async def fetch(self, issuer: str) -> OidcMetadata:
        """Return the (cached) discovery metadata for ``issuer`` or raise
        :class:`DiscoveryError`."""
        base = _normalize_issuer(issuer)
        cached = self._cache.get(base)
        if cached is not None and self._fresh(cached):
            return cached.metadata
        async with self._lock_for(base):
            cached = self._cache.get(base)  # double-check under the lock
            if cached is not None and self._fresh(cached):
                return cached.metadata
            metadata = await self._fetch(base)
            self._cache[base] = _CachedMetadata(
                metadata=metadata, fetched_at=time.monotonic()
            )
            return metadata

    async def _fetch(self, base_issuer: str) -> OidcMetadata:
        url = f"{base_issuer}{_WELL_KNOWN_SUFFIX}"
        try:
            document = await fetch_json(
                url,
                client_factory=self._client_factory,
                timeout_seconds=self._timeout,
                max_response_bytes=self._max_bytes,
            )
        except OidcHttpError as exc:
            raise DiscoveryError(f"discovery fetch failed: {exc}") from exc
        return _parse_metadata(document, expected_issuer=base_issuer)

    def _fresh(self, cached: _CachedMetadata) -> bool:
        return (time.monotonic() - cached.fetched_at) < self._cache_ttl

    def _lock_for(self, base_issuer: str) -> asyncio.Lock:
        lock = self._locks.get(base_issuer)
        if lock is None:
            lock = self._locks.setdefault(base_issuer, asyncio.Lock())
        return lock


def _normalize_issuer(issuer: str) -> str:
    base = issuer.strip()
    if base.endswith(_WELL_KNOWN_SUFFIX):
        base = base[: -len(_WELL_KNOWN_SUFFIX)]
    return base.rstrip("/")


def _parse_metadata(document: Any, *, expected_issuer: str) -> OidcMetadata:
    if not isinstance(document, dict):
        raise DiscoveryError("discovery document is not a JSON object")

    # The issuer in the document must match the one we discovered against —
    # otherwise a provider could point trust at an identity we didn't configure.
    doc_issuer = document.get("issuer")
    if (
        not isinstance(doc_issuer, str)
        or _normalize_issuer(doc_issuer) != expected_issuer
    ):
        raise DiscoveryError(
            f"discovery issuer {doc_issuer!r} does not match {expected_issuer!r}"
        )

    endpoints = {}
    for field in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
        value = document.get(field)
        if not isinstance(value, str) or not value:
            raise DiscoveryError(f"discovery document missing {field}")
        try:
            require_https(value)
        except OidcHttpError as exc:
            raise DiscoveryError(f"{field} is not https: {exc}") from exc
        endpoints[field] = value

    algs = document.get("id_token_signing_alg_values_supported")
    alg_tuple: tuple[str, ...] | None = None
    if isinstance(algs, list) and all(isinstance(a, str) for a in algs):
        alg_tuple = tuple(algs)

    return OidcMetadata(
        issuer=expected_issuer,
        authorization_endpoint=endpoints["authorization_endpoint"],
        token_endpoint=endpoints["token_endpoint"],
        jwks_uri=endpoints["jwks_uri"],
        id_token_signing_alg_values_supported=alg_tuple,
    )
