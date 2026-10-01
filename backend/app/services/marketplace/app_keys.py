"""The keys an app signs with, from its registration.

A registration carries its key set in one of two ways, or both: pasted into the
registration (``jwks``), or published by the app at ``jwks_uri``. The pasted
set is parsed with the registration snapshot. A published set is fetched here,
from the app's own origin over https, and reused for :data:`CACHE_TTL_SECONDS`,
the same bound the snapshot keeps. A rotation is the app publishing its new key
beside the old one; the next fetch picks it up.

A key named in both sets is the pasted one.

An operator's **Connect** reads the set the app serves at :data:`KEY_SET_PATH`
under its base URL with :func:`read_key_set`, shows each key's
:func:`jwk_thumbprint`, and pastes the set it confirms. That is how an app on
a plain-http address inside the deployment's network gets its keys pinned.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import time
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping, Optional
from urllib.parse import urlparse

import httpx
from jwt import PyJWK

from app.services.marketplace.registration_lookup import (
    CACHE_TTL_SECONDS,
    RegistrationSnapshot,
)
from app.services.safe_http import ResponseTooLargeError, request_public_target
from app.services.webhook_target_url import (
    WebhookTargetUrlError,
    WebhookTargetUrlPrivateError,
)

logger = logging.getLogger(__name__)

__all__ = [
    "JWKS_MAX_BYTES",
    "KEY_SET_PATH",
    "KeySetUnreadableError",
    "PRIVATE_JWK_MEMBERS",
    "PUBLIC_JWK_TYPES",
    "clear_fetched_keys",
    "jwk_thumbprint",
    "jwks_uri_allowed",
    "key_for",
    "key_set_url",
    "read_key_set",
]

#: The largest key set document read. A key set is a handful of public keys.
JWKS_MAX_BYTES = 64 * 1024

#: Key types a verification key may be. ``oct`` is absent deliberately: a
#: symmetric key is the signing key, and a key set holds the half that is
#: meant to be read.
PUBLIC_JWK_TYPES: frozenset[str] = frozenset({"RSA", "EC", "OKP"})

#: JWK members that only ever appear on a private key (RFC 7517 §9.3 / RFC
#: 7518). Their presence means the whole key was given, not its public half.
PRIVATE_JWK_MEMBERS: frozenset[str] = frozenset(
    {"d", "p", "q", "dp", "dq", "qi", "oth", "k"}
)

#: The members a key's RFC 7638 thumbprint is computed over, by key type.
_THUMBPRINT_MEMBERS: Mapping[str, tuple[str, ...]] = MappingProxyType(
    {
        "RSA": ("e", "kty", "n"),
        "EC": ("crv", "kty", "x", "y"),
        "OKP": ("crv", "kty", "x"),
    }
)

#: Where an app serves its key set, under its base URL.
KEY_SET_PATH = "/.well-known/jwks.json"

#: Per-fetch budget, connect and read capped separately.
_TIMEOUT = httpx.Timeout(5.0, connect=5.0)


class KeySetUnreadableError(Exception):
    """A key set address that did not answer 200 with a JSON document."""


def _origin(url: str) -> Optional[tuple[str, str, Optional[int]]]:
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.hostname:
        return None
    return parsed.scheme.lower(), parsed.hostname.lower(), parsed.port


def jwks_uri_allowed(jwks_uri: str, base_url: str) -> bool:
    """Whether ``jwks_uri`` is https and on ``base_url``'s own origin.

    Asked when the address is stored and again before every fetch, since the
    base URL may have moved since.
    """
    uri_origin = _origin(jwks_uri)
    if uri_origin is None or uri_origin[0] != "https":
        return False
    return uri_origin == _origin(base_url)


def key_set_url(base_url: str) -> str:
    """Where the app at ``base_url`` serves its key set."""
    return f"{base_url.rstrip('/')}{KEY_SET_PATH}"


def jwk_thumbprint(entry: Mapping[str, Any]) -> str:
    """A public key's RFC 7638 SHA-256 thumbprint, base64url without padding.

    The fingerprint an app logs for its key, so an operator can match the two.
    ``entry`` is a public key of a type in :data:`PUBLIC_JWK_TYPES`.
    """
    members = _THUMBPRINT_MEMBERS[entry["kty"]]
    canonical = json.dumps(
        {name: entry[name] for name in members}, separators=(",", ":"), sort_keys=True
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


@dataclass(frozen=True)
class _Fetched:
    keys: Mapping[str, Any]
    fetched_at: float


_fetched: dict[str, _Fetched] = {}


def clear_fetched_keys() -> None:
    """Forget every fetched key set."""
    _fetched.clear()


def _parse(document: Any, source: str) -> Mapping[str, Any]:
    """The ``kid`` → public key index of a fetched key set.

    Only public asymmetric keys with a ``kid`` are kept; anything else in the
    document is left out.
    """
    parsed: dict[str, Any] = {}
    entries = document.get("keys") if isinstance(document, dict) else None
    for entry in entries if isinstance(entries, list) else []:
        if not isinstance(entry, dict):
            continue
        kid = entry.get("kid")
        if not isinstance(kid, str) or not kid or kid in parsed:
            continue
        if entry.get("kty") not in PUBLIC_JWK_TYPES:
            continue
        if PRIVATE_JWK_MEMBERS.intersection(entry):
            continue
        try:
            parsed[kid] = PyJWK.from_dict(entry).key
        except Exception:
            logger.warning("app keys: %s has an unusable key %r", source, kid)
    return MappingProxyType(parsed)


async def read_key_set(
    url: str, *, transport: httpx.AsyncBaseTransport | None = None
) -> Any:
    """The JSON document an app serves at ``url``.

    Fetched the way Initiative calls the app: a private address is allowed,
    and plain http only to one. Raises :class:`KeySetUnreadableError`.
    """
    try:
        response = await request_public_target(
            "GET",
            url,
            headers={"Accept": "application/json"},
            timeout=_TIMEOUT,
            transport=transport,
            allow_private=True,
            max_bytes=JWKS_MAX_BYTES,
        )
    except (
        WebhookTargetUrlError,
        WebhookTargetUrlPrivateError,
        ResponseTooLargeError,
        httpx.HTTPError,
    ) as exc:
        raise KeySetUnreadableError(str(exc) or type(exc).__name__) from exc
    if response.status_code != 200:
        raise KeySetUnreadableError(f"answered {response.status_code}")
    try:
        return json.loads(response.content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise KeySetUnreadableError("did not answer with JSON") from exc


async def _fetch(
    jwks_uri: str, transport: httpx.AsyncBaseTransport | None
) -> Mapping[str, Any]:
    """Read one published key set. A failure is an empty set, logged."""
    try:
        document = await read_key_set(jwks_uri, transport=transport)
    except KeySetUnreadableError as exc:
        logger.warning("app keys: %s could not be read (%s)", jwks_uri, exc)
        return MappingProxyType({})
    return _parse(document, jwks_uri)


async def _published_keys(
    registration: RegistrationSnapshot,
    *,
    now: float,
    transport: httpx.AsyncBaseTransport | None,
) -> Mapping[str, Any]:
    jwks_uri = registration.jwks_uri
    if not jwks_uri:
        return MappingProxyType({})
    if not jwks_uri_allowed(jwks_uri, registration.base_url):
        logger.warning(
            "app keys: %s key set address is not on its base URL's origin",
            registration.public_id,
        )
        return MappingProxyType({})
    cached = _fetched.get(jwks_uri)
    if cached is not None and now - cached.fetched_at < CACHE_TTL_SECONDS:
        return cached.keys
    keys = await _fetch(jwks_uri, transport)
    _fetched[jwks_uri] = _Fetched(keys=keys, fetched_at=now)
    return keys


async def key_for(
    registration: RegistrationSnapshot,
    kid: str,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> Optional[Any]:
    """The public key ``kid`` names in this registration's key sets, or
    ``None``: the pasted set first, then the published one."""
    if not kid:
        return None
    pasted = registration.keys.get(kid)
    if pasted is not None:
        return pasted
    published = await _published_keys(
        registration, now=time.monotonic(), transport=transport
    )
    return published.get(kid)
