"""Verify an OpenID Connect ``id_token``.

A pure, network-free function of the raw token and its trust parameters — the
caller resolves the signing key first (production: the provider's JWKS; tests: a
local keypair) — so it can be tested in isolation.

Verification is strict, and the rules are enforced here rather than left to
library defaults:

* **asymmetric-only algorithm allowlist** (``RS*``/``PS*``/``ES*``/``EdDSA``);
  HMAC and ``none`` are not accepted;
* **required registered claims** ``iss``/``sub``/``aud``/``exp``/``iat``;
* **audience + issuer** bound to the configured provider;
* **``azp`` checked** for multi-audience tokens;
* **constant-time ``nonce`` match**.

Any failure raises :class:`IdTokenVerificationError` — fail-closed. Built on
PyJWT; see the auth design doc for the rationale.
"""

from __future__ import annotations

import hmac
from collections.abc import Sequence
from typing import Any

import jwt

# Asymmetric signature algorithms only. HMAC (``HS*``) and ``none`` are excluded
# by construction so they can't be selected — not merely discouraged.
ASYMMETRIC_ALGORITHMS: frozenset[str] = frozenset(
    {
        "RS256",
        "RS384",
        "RS512",
        "PS256",
        "PS384",
        "PS512",
        "ES256",
        "ES384",
        "ES512",
        "EdDSA",
    }
)

# Registered claims an OIDC id_token MUST carry (OIDC Core §2). Requiring
# ``exp``/``iat`` here means a token without an expiry can never be mistaken for
# a non-expiring one.
_REQUIRED_CLAIMS: tuple[str, ...] = ("iss", "sub", "aud", "exp", "iat")

# Default allowlist: the two ubiquitous asymmetric algs. Callers may *narrow* it
# (e.g. to what the provider's JWKS advertises); widening past the asymmetric
# set is refused below.
DEFAULT_ALGORITHMS: tuple[str, ...] = ("RS256", "ES256")

# Clock-skew tolerance applied to ``exp``/``iat``/``nbf`` (seconds).
DEFAULT_LEEWAY_SECONDS: int = 60


class IdTokenVerificationError(Exception):
    """An id_token failed verification and MUST be rejected (no login)."""


def verify_id_token(
    raw_token: str,
    *,
    signing_key: Any,
    issuer: str,
    audience: str,
    nonce: str,
    algorithms: Sequence[str] = DEFAULT_ALGORITHMS,
    leeway_seconds: int = DEFAULT_LEEWAY_SECONDS,
) -> dict[str, Any]:
    """Verify ``raw_token`` against a trusted ``signing_key`` and return its
    claims, or raise :class:`IdTokenVerificationError`.

    ``signing_key`` is the provider's *public* key (a ``PyJWK.key``, a
    ``cryptography`` public-key object, or PEM) already resolved from the
    provider's JWKS by ``kid``. ``issuer`` / ``audience`` are the configured
    provider's issuer and our ``client_id``. ``nonce`` is the exact value this
    login attempt sent to the IdP — a missing or mismatched nonce is fatal.

    Raises :class:`ValueError` (not :class:`IdTokenVerificationError`) for a
    caller misconfiguration — an empty or non-asymmetric algorithm allowlist, or
    an empty issuer, audience, or nonce — since those are programming errors.
    """
    requested = tuple(algorithms)
    if not requested:
        raise ValueError("id_token algorithms allowlist must be non-empty")
    illegal = sorted(a for a in requested if a not in ASYMMETRIC_ALGORITHMS)
    if illegal:
        # The allowlist is asymmetric by contract — refuse a symmetric/``none`` alg.
        raise ValueError(f"id_token algorithms must be asymmetric; refused {illegal}")
    # All three trust anchors must be non-empty (PyJWT rejects empty iss/aud too,
    # but silently — surface it as an explicit caller error).
    if not issuer:
        raise ValueError("an issuer is required to verify an id_token")
    if not audience:
        raise ValueError("an audience is required to verify an id_token")
    if not nonce:
        raise ValueError("a nonce is required to verify an id_token")

    try:
        claims: dict[str, Any] = jwt.decode(
            raw_token,
            key=signing_key,
            algorithms=list(requested),
            audience=audience,
            issuer=issuer,
            leeway=leeway_seconds,
            options={
                "require": list(_REQUIRED_CLAIMS),
                "verify_signature": True,
                "verify_aud": True,
                "verify_iss": True,
                "verify_exp": True,
            },
        )
    except jwt.PyJWTError as exc:
        # Fail-closed: any PyJWT failure rejects the token.
        raise IdTokenVerificationError(f"id_token rejected: {exc}") from exc

    _verify_nonce(claims, nonce)
    _verify_azp(claims, audience)
    return claims


def _verify_nonce(claims: dict[str, Any], expected: str) -> None:
    """Constant-time ``nonce`` match; a missing or non-string nonce is rejected."""
    got = claims.get("nonce")
    if not isinstance(got, str) or not hmac.compare_digest(got, expected):
        raise IdTokenVerificationError("id_token nonce does not match this login")


def _verify_azp(claims: dict[str, Any], audience: str) -> None:
    """Enforce ``azp`` (OIDC Core §3.1.3.7). PyJWT confirms our ``audience`` is
    *present in* ``aud`` but does not check the authorized party: when a token is
    issued to multiple audiences ``azp`` MUST be present and equal our
    ``client_id``, and whenever ``azp`` is present at all it must match.
    """
    azp = claims.get("azp")
    aud = claims.get("aud")
    multi_aud = isinstance(aud, (list, tuple)) and len(aud) > 1
    if multi_aud and azp is None:
        raise IdTokenVerificationError("id_token has multiple audiences but no azp")
    if azp is not None and azp != audience:
        raise IdTokenVerificationError("id_token azp does not match client_id")
