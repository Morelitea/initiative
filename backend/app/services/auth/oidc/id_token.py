"""Secure verification of an OpenID Connect ``id_token``.

The crown jewel of the OIDC relying-party flow: a bug here is an authentication
bypass. It is deliberately a **pure, network-free** function of the raw token
plus its trust parameters — the caller resolves the signing key beforehand (in
production from the provider's JWKS via ``PyJWKClient``; in tests from a local
keypair) — so the verification logic can be exercised adversarially in isolation.

Built on PyJWT ``>=2.13.0`` rather than Authlib (history/auth-detailed-design.md
§10a). The industry's 2026 CVE wave showed the dangerous class here is the
id_token **fail-open** — an unrecognized ``alg`` silently accepted, RS/HS
algorithm confusion, or a stripped ``alg:none`` signature. That is a *usage*
property, so it is enforced HERE, in our code, never delegated to a library
default:

* **asymmetric-only algorithm allowlist** — HMAC and ``none`` are structurally
  unrepresentable, so an attacker can neither re-sign the token with the
  (public) signing key as an HMAC secret nor strip the signature;
* **required registered claims** — ``iss``/``sub``/``aud``/``exp``/``iat`` must
  be present (a missing ``exp`` can never yield a non-expiring token);
* **audience + issuer** bound to the configured provider;
* **``azp`` enforced** when the token is issued to multiple audiences;
* **constant-time ``nonce`` match** — binds the token to *this* login attempt
  (replay / token-injection defense).

Any failure raises :class:`IdTokenVerificationError` — the verifier is
fail-closed, so an unforeseen error rejects the token rather than admitting it.
"""

from __future__ import annotations

import hmac
from collections.abc import Sequence
from typing import Any

import jwt

# Asymmetric signature algorithms only. HMAC (``HS*``) and ``none`` are
# deliberately absent: allowing an ``HS*`` alg alongside a public verification
# key is the classic algorithm-confusion bypass (the attacker signs with the
# known public key as the HMAC secret), and ``none`` strips the signature
# entirely. Keeping the set asymmetric-only makes both *unrepresentable* rather
# than merely discouraged — a caller cannot re-enable them by accident.
_ASYMMETRIC_ALGORITHMS: frozenset[str] = frozenset(
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
    an empty nonce — because those are programming errors, not attacker input.
    """
    requested = tuple(algorithms)
    if not requested:
        raise ValueError("id_token algorithms allowlist must be non-empty")
    illegal = sorted(a for a in requested if a not in _ASYMMETRIC_ALGORITHMS)
    if illegal:
        # Refuse to even run with a symmetric / ``none`` alg in the allowlist —
        # that would reopen the confusion/strip bypass this module exists to shut.
        raise ValueError(f"id_token algorithms must be asymmetric; refused {illegal}")
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
        # Fail-closed: any PyJWT failure — bad signature, disallowed alg /
        # ``alg:none``, wrong aud/iss, expired, missing required claim, malformed
        # token, unusable key — rejects the token.
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
