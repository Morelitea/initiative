"""The credential Initiative presents when it calls a plug-in service.

A context token is deliberately the smallest thing that can work. It names
**one guild**, **one install**, **one scope**, and lives about a minute, so what
a plug-in holds at any moment is an answer to the call in front of it rather than a
standing key to a deployment. Three properties are worth stating because they
are what the shape buys:

* **Guild-pinned and per-call.** ``community_ref`` is a claim, not a parameter, and
  the token is minted for the request it accompanies. A plug-in never holds a
  credential naming more than one guild, and never holds one for long.
* **It carries no person's details.** There is no ``sub``, no email, no
  display name. Where a source needs a member's own vendor credential the token carries
  ``connection_refs`` — the opaque handles from :mod:`app.services.tenant.
  plugin_connections` — so the plug-in selects the right credential while learning
  nothing about who the member is. The page handoff is the one channel that
  carries a real identity, because that is a person's session crossing into an
  interactive surface; this one is the platform calling a service. A block's
  call names who is looking (``viewer``, their reference at this install) only
  where the answer depends on it: a ``per_viewer`` read, or an action.
* **Its audience is one plug-in.** ``aud`` is ``initiative-plugin:<public_id>``, so a
  token minted for one plug-in is not accepted by another even if it is somehow
  handed over.

A ``lifecycle`` token is Initiative calling one of the plug-in's hooks while it
runs a connection's flow or ends one; its ``hook`` claim names which, so a token
minted for one hook is not spent on another.

Verification is public: :func:`context_jwks` publishes the public half as a JWKS
document, stamped with the same ``kid`` the token header carries, so a plug-in can
verify and an operator can rotate without a coordinated restart.

The keypair is dedicated and has no fallback (see
:func:`app.core.security.resolve_plugin_platform_signing_material`): the one in
``PLUGIN_PLATFORM_SIGNING_PRIVATE_KEY_PEM``, or else the one the deployment
generated and stored. With neither loaded this module raises, and callers turn
that into a fail-closed 503 rather than signing plug-in traffic with some other
boundary's key.
"""

from __future__ import annotations

import base64
import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Optional, Sequence

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.core.security import (
    HANDOFF_JWT_ALGORITHM,
    PLUGIN_CONTEXT_TOKEN_TYPE,
    TOKEN_ISSUER,
    plugin_platform_audience,
    resolve_plugin_platform_signing_material,
    sign_rs256,
)

__all__ = [
    "CONTEXT_SCOPES",
    "CONTEXT_TOKEN_LIFETIME",
    "ContextTokenError",
    "context_jwks",
    "generate_signing_key",
    "key_thumbprint",
    "mint_context_token",
]

#: What a token may authorize. Closed, and pinned per call: ``endpoint`` reaches
#: one declared endpoint, ``lifecycle`` tells a plug-in an install changed. A token
#: minted for one is not usable for the other.
#:
#: One scope covers reads and writes because both are calls to a declared
#: endpoint, and ``endpoint_id`` is what narrows it: a token minted to read the
#: issue count cannot be spent closing an issue. The endpoint's own ``direction``
#: says which it was, and the plug-in knows it without being told.
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


def generate_signing_key() -> str:
    """A new 2048-bit RSA signing key, as an unencrypted PKCS #8 PEM."""
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode("ascii")


def key_thumbprint(private_pem: str) -> str:
    """The RFC 7638 SHA-256 thumbprint of an RSA key's public half, base64url."""
    private_key = serialization.load_pem_private_key(
        private_pem.encode("utf-8"), password=None
    )
    if not isinstance(private_key, rsa.RSAPrivateKey):
        raise ContextTokenError("the plug-in platform signing key must be an RSA key")
    numbers = private_key.public_key().public_numbers()
    members = {"e": _b64u(numbers.e), "kty": "RSA", "n": _b64u(numbers.n)}
    canonical = json.dumps(members, separators=(",", ":"), sort_keys=True)
    digest = hashlib.sha256(canonical.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def mint_context_token(
    *,
    public_id: str,
    guild_ref: str,
    plugin_install_id: int,
    scope: str,
    endpoint_id: Optional[str] = None,
    hook: Optional[str] = None,
    connection_refs: Optional[Mapping[str, str]] = None,
    caller: Optional[str] = None,
    actor: Optional[str] = None,
    member: Optional[str] = None,
    initiative_id: Optional[int] = None,
    task_ids: Optional[Sequence[int]] = None,
    viewer: Optional[str] = None,
    lifetime: timedelta = CONTEXT_TOKEN_LIFETIME,
) -> tuple[str, int]:
    """Sign one context token and return it with its lifetime in seconds.

    ``guild_ref`` is what this install calls the guild — the same sector the
    member references use, so a plug-in installed twice holds two unrelated values
    for one guild. No row id of ours is a parameter here.

    ``connection_refs`` maps a connection id to the opaque handle the plug-in knows
    that member's credential by. It is present only where the call genuinely
    depends on a per-member credential; a call satisfied by guild-scoped
    connections alone carries no user-derived claim at all.

    A call another plug-in made through Initiative also names that plug-in
    (``caller``, as ``act.sub``, RFC 8693 §4.1), whose behalf it is on
    (``actor``: ``installation`` or ``member``), the member by this install's
    own reference for them (``member``), and the initiative the caller's token
    is narrowed to (``initiative_id``), each only when it applies.

    A block's call names the tasks it is about (``task_ids``) and, for a
    ``per_viewer`` read or an action, the member looking at them by this
    install's reference for them (``viewer``).
    """
    if scope not in CONTEXT_SCOPES:
        raise ContextTokenError(f"unknown context scope {scope!r}")
    refs = dict(connection_refs or {})
    if len(refs) > _MAX_CONNECTION_REFS:
        raise ContextTokenError("too many connection references for one call")

    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "jti": str(uuid.uuid4()),
        "iss": TOKEN_ISSUER,
        "aud": plugin_platform_audience(public_id),
        "iat": int(now.timestamp()),
        "exp": now + lifetime,
        "community_ref": guild_ref,
        "plugin_install_id": plugin_install_id,
        "scope": scope,
    }
    # Each optional claim appears only when it means something, so a plug-in can
    # read presence rather than having to distinguish null from absent.
    if endpoint_id is not None:
        payload["endpoint_id"] = endpoint_id
    if hook is not None:
        payload["hook"] = hook
    if refs:
        payload["connection_refs"] = refs
    if caller is not None:
        payload["act"] = {"sub": caller}
    if actor is not None:
        payload["actor"] = actor
    if member is not None:
        payload["member"] = member
    if initiative_id is not None:
        payload["initiative_id"] = initiative_id
    if task_ids is not None:
        payload["task_ids"] = list(task_ids)
    if viewer is not None:
        payload["viewer"] = viewer

    token = sign_rs256(
        payload,
        *resolve_plugin_platform_signing_material(),
        typ=PLUGIN_CONTEXT_TOKEN_TYPE,
    )
    return token, int(lifetime.total_seconds())


#: The published document, rebuilt only when the configured key changes. Parsing
#: a PEM per request would be pure waste on a route plug-ins poll.
_jwks_cache: tuple[str, Optional[str], dict[str, Any]] | None = None


def context_jwks() -> dict[str, Any]:
    """The public half of the signing key, as a JWKS document.

    Serves exactly the key this build signs with, carrying the same ``kid`` the
    token header stamps, so a plug-in picks the right entry while a rotation is in
    flight. Raises when no keypair is configured — the caller answers that as
    configuration rather than publishing an empty key set, which a plug-in would
    cache as "this deployment has no keys".
    """
    global _jwks_cache

    private_pem, kid = resolve_plugin_platform_signing_material()
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
            "PLUGIN_PLATFORM_SIGNING_PRIVATE_KEY_PEM is not a readable private key"
        ) from exc
    if not isinstance(private_key, rsa.RSAPrivateKey):
        raise ContextTokenError(
            "PLUGIN_PLATFORM_SIGNING_PRIVATE_KEY_PEM must be an RSA key for RS256"
        )

    numbers = private_key.public_key().public_numbers()
    entry: dict[str, Any] = {
        "kty": "RSA",
        "use": "sig",
        "alg": HANDOFF_JWT_ALGORITHM,
        "n": _b64u(numbers.n),
        "e": _b64u(numbers.e),
    }
    if kid:
        entry["kid"] = kid
    document = {"keys": [entry]}
    _jwks_cache = (private_pem, kid, document)
    return document
