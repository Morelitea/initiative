"""The credential Initiative presents when it calls an app service.

A context token is deliberately the smallest thing that can work. It names
**one guild**, **one install**, **one scope**, and lives about a minute, so what
an app holds at any moment is an answer to the call in front of it rather than a
standing key to a deployment. Three properties are worth stating because they
are what the shape buys:

* **Guild-pinned and per-call.** ``guild_id`` is a claim, not a parameter, and
  the token is minted for the request it accompanies. An app never holds a
  credential naming more than one guild, and never holds one for long.
* **It carries no person.** There is no ``sub``, no email, no display name. Where
  a source needs a member's own vendor credential the token carries
  ``connection_refs`` — the opaque handles from :mod:`app.services.tenant.
  app_connections` — so the app selects the right credential while learning
  nothing about who the member is. The embed handoff is the one channel that
  carries a real identity, because that is a person's session crossing into an
  interactive surface; this one is the platform calling a service.
* **Its audience is one app.** ``aud`` is ``initiative-app:<public_id>``, so a
  token minted for one app is not accepted by another even if it is somehow
  handed over.

Verification is public: :func:`context_jwks` publishes the public half as a JWKS
document, stamped with the same ``kid`` the token header carries, so an app can
verify and an operator can rotate without a coordinated restart.

The keypair is dedicated and has no fallback (see
:func:`app.core.security.resolve_app_platform_signing_material`). With it unset
this module raises, and callers turn that into a fail-closed 503 rather than
signing app traffic with some other boundary's key.
"""

from __future__ import annotations

import base64
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Optional

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.core.config import settings
from app.core.security import (
    app_platform_audience,
    resolve_app_platform_signing_material,
)

__all__ = [
    "CONTEXT_SCOPES",
    "CONTEXT_TOKEN_LIFETIME",
    "ContextTokenError",
    "context_jwks",
    "mint_context_token",
]

#: What a token may authorize. Closed, and pinned per call: ``endpoint`` reaches
#: one declared endpoint, ``lifecycle`` tells an app an install changed. A token
#: minted for one is not usable for the other.
#:
#: One scope covers reads and writes because both are calls to a declared
#: endpoint, and ``endpoint_id`` is what narrows it: a token minted to read the
#: issue count cannot be spent closing an issue. The endpoint's own ``direction``
#: says which it was, and the app knows it without being told.
CONTEXT_SCOPES: frozenset[str] = frozenset({"endpoint", "lifecycle"})

#: About a minute. Long enough to survive a slow round trip and a little clock
#: skew, short enough that a captured token is spent before it is useful.
CONTEXT_TOKEN_LIFETIME = timedelta(seconds=60)

#: How many opaque connection handles one call may carry. A source's ``requires``
#: is already capped at ten terms; this is the same bound restated where the
#: value is built.
_MAX_CONNECTION_REFS = 10


class ContextTokenError(RuntimeError):
    """The token could not be built from what was asked for."""


def _b64u(value: int) -> str:
    """A JWKS integer: big-endian bytes, base64url, no padding."""
    length = max(1, (value.bit_length() + 7) // 8)
    return base64.urlsafe_b64encode(value.to_bytes(length, "big")).rstrip(b"=").decode()


def mint_context_token(
    *,
    public_id: str,
    guild_id: int,
    app_install_id: int,
    scope: str,
    endpoint_id: Optional[str] = None,
    connection_refs: Optional[Mapping[str, str]] = None,
    lifetime: timedelta = CONTEXT_TOKEN_LIFETIME,
) -> tuple[str, int]:
    """Sign one context token and return it with its lifetime in seconds.

    ``connection_refs`` maps a connection id to the opaque handle the app knows
    that member's credential by. It is present only where the call genuinely
    depends on a per-member credential; a call satisfied by guild-scoped
    connections alone carries no user-derived claim at all.
    """
    if scope not in CONTEXT_SCOPES:
        raise ContextTokenError(f"unknown context scope {scope!r}")
    refs = dict(connection_refs or {})
    if len(refs) > _MAX_CONNECTION_REFS:
        raise ContextTokenError("too many connection references for one call")

    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "jti": str(uuid.uuid4()),
        "iss": settings.APP_PLATFORM_ISSUER,
        "aud": app_platform_audience(public_id),
        "iat": int(now.timestamp()),
        "exp": now + lifetime,
        "guild_id": guild_id,
        "app_install_id": app_install_id,
        "scope": scope,
    }
    # Each optional claim appears only when it means something, so an app can
    # read presence rather than having to distinguish null from absent.
    if endpoint_id is not None:
        payload["endpoint_id"] = endpoint_id
    if refs:
        payload["connection_refs"] = refs

    key, algorithm, kid = resolve_app_platform_signing_material()
    headers: dict[str, Any] | None = {"kid": kid} if kid else None
    token = jwt.encode(payload, key, algorithm=algorithm, headers=headers)
    return token, int(lifetime.total_seconds())


#: The published document, rebuilt only when the configured key changes. Parsing
#: a PEM per request would be pure waste on a route apps poll.
_jwks_cache: tuple[str, Optional[str], dict[str, Any]] | None = None


def context_jwks() -> dict[str, Any]:
    """The public half of the signing key, as a JWKS document.

    Serves exactly the key this build signs with, carrying the same ``kid`` the
    token header stamps, so an app picks the right entry while a rotation is in
    flight. Raises when no keypair is configured — the caller answers that as
    configuration rather than publishing an empty key set, which an app would
    cache as "this deployment has no keys".
    """
    global _jwks_cache

    private_pem, algorithm, kid = resolve_app_platform_signing_material()
    if _jwks_cache is not None:
        cached_pem, cached_kid, document = _jwks_cache
        if cached_pem == private_pem and cached_kid == kid:
            return document

    try:
        private_key = serialization.load_pem_private_key(
            private_pem.encode("utf-8"), password=None
        )
    except (ValueError, TypeError) as exc:
        raise ContextTokenError(
            "APP_PLATFORM_SIGNING_PRIVATE_KEY_PEM is not a readable private key"
        ) from exc
    if not isinstance(private_key, rsa.RSAPrivateKey):
        raise ContextTokenError(
            "APP_PLATFORM_SIGNING_PRIVATE_KEY_PEM must be an RSA key for RS256"
        )

    numbers = private_key.public_key().public_numbers()
    entry: dict[str, Any] = {
        "kty": "RSA",
        "use": "sig",
        "alg": algorithm,
        "n": _b64u(numbers.n),
        "e": _b64u(numbers.e),
    }
    if kid:
        entry["kid"] = kid
    document = {"keys": [entry]}
    _jwks_cache = (private_pem, kid, document)
    return document
