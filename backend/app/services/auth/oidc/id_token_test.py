"""Adversarial tests for the OIDC id_token verifier.

A bug in this module is an authentication bypass, so the suite is written as
attacks: for every way a forged or malformed token could sneak through, assert
it is rejected. Tokens are minted with locally-generated RSA/EC keys (no
network), so the verification logic is exercised in complete isolation.
"""

from __future__ import annotations

import base64
import hashlib
import hmac as stdlib_hmac
import json
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa

from app.services.auth.oidc.id_token import (
    IdTokenVerificationError,
    verify_id_token,
)

pytestmark = pytest.mark.unit

ISSUER = "https://idp.example.com"
AUDIENCE = "client-123"
NONCE = "nonce-abc"

# Sentinel: pass as an override value to DROP that claim entirely.
_DROP = object()


def _pem_private(key) -> str:
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()


def _pem_public(key) -> str:
    return key.public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()


def _rsa_keypair() -> tuple[str, str]:
    priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return _pem_private(priv), _pem_public(priv.public_key())


def _ec_keypair() -> tuple[str, str]:
    priv = ec.generate_private_key(ec.SECP256R1())
    return _pem_private(priv), _pem_public(priv.public_key())


# One keypair per family, generated once for the module.
RSA_PRIV, RSA_PUB = _rsa_keypair()
EC_PRIV, EC_PUB = _ec_keypair()


def _claims(**overrides) -> dict:
    now = datetime.now(timezone.utc)
    base = {
        "iss": ISSUER,
        "sub": "user-1",
        "aud": AUDIENCE,
        "exp": now + timedelta(minutes=5),
        "iat": now,
        "nonce": NONCE,
    }
    for key, value in overrides.items():
        if value is _DROP:
            base.pop(key, None)
        else:
            base[key] = value
    return base


def _encode(claims: dict, *, priv: str = RSA_PRIV, alg: str = "RS256") -> str:
    return jwt.encode(claims, priv, algorithm=alg)


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _forge_hs256(claims: dict, secret: str) -> str:
    """Hand-roll an HS256 token with ``secret`` as the HMAC key.

    Done manually because PyJWT's ``encode`` refuses to HMAC-sign with a PEM
    public key (its own confusion guard) — we need the malicious token to exist
    so the *verifier's* asymmetric-only allowlist is what rejects it. Claims use
    integer timestamps so they're plain-JSON serializable.
    """
    header = _b64url(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    body = _b64url(json.dumps(claims).encode())
    signing_input = f"{header}.{body}"
    sig = stdlib_hmac.new(
        secret.encode(), signing_input.encode(), hashlib.sha256
    ).digest()
    return f"{signing_input}.{_b64url(sig)}"


def _verify(token: str, **overrides):
    kwargs = dict(
        signing_key=RSA_PUB,
        issuer=ISSUER,
        audience=AUDIENCE,
        nonce=NONCE,
    )
    kwargs.update(overrides)
    return verify_id_token(token, **kwargs)


# --- happy paths ------------------------------------------------------------


def test_valid_rs256_token_accepted():
    claims = _verify(_encode(_claims()))
    assert claims["sub"] == "user-1"
    assert claims["nonce"] == NONCE


def test_valid_es256_token_accepted():
    token = _encode(_claims(), priv=EC_PRIV, alg="ES256")
    claims = _verify(token, signing_key=EC_PUB, algorithms=["ES256"])
    assert claims["sub"] == "user-1"


def test_multi_aud_with_correct_azp_accepted():
    token = _encode(_claims(aud=[AUDIENCE, "other-app"], azp=AUDIENCE))
    claims = _verify(token)
    assert claims["azp"] == AUDIENCE


# --- signature / algorithm attacks -----------------------------------------


def test_alg_none_rejected():
    """A stripped (unsigned) token must never be accepted."""
    token = jwt.encode(_claims(), key="", algorithm="none")
    with pytest.raises(IdTokenVerificationError):
        _verify(token)


def test_hs256_confusion_rejected():
    """Algorithm confusion: attacker forges an HS256 token using the *public*
    key as the shared secret. HS256 isn't in the asymmetric allowlist, so it's
    refused before any signature check."""
    now = int(datetime.now(timezone.utc).timestamp())
    claims = {
        "iss": ISSUER,
        "sub": "user-1",
        "aud": AUDIENCE,
        "exp": now + 300,
        "iat": now,
        "nonce": NONCE,
    }
    forged = _forge_hs256(claims, RSA_PUB)
    with pytest.raises(IdTokenVerificationError):
        _verify(forged)


def test_tampered_signature_rejected():
    token = _encode(_claims())
    header, payload, sig = token.split(".")
    i = len(sig) // 2
    sig = sig[:i] + ("A" if sig[i] != "A" else "B") + sig[i + 1 :]
    with pytest.raises(IdTokenVerificationError):
        _verify(f"{header}.{payload}.{sig}")


def test_token_signed_by_a_different_key_rejected():
    other_priv, _ = _rsa_keypair()
    token = jwt.encode(_claims(), other_priv, algorithm="RS256")
    with pytest.raises(IdTokenVerificationError):
        _verify(token)


def test_token_alg_outside_narrowed_allowlist_rejected():
    """The token's *actual* alg must be in the allowlist — narrowing to ES256
    rejects an RS256 token (not a caller error: ES256 is legal, the token isn't)."""
    with pytest.raises(IdTokenVerificationError):
        _verify(_encode(_claims()), algorithms=["ES256"])


# --- claim attacks ----------------------------------------------------------


def test_expired_token_rejected():
    token = _encode(_claims(exp=datetime.now(timezone.utc) - timedelta(minutes=5)))
    with pytest.raises(IdTokenVerificationError):
        _verify(token)


def test_wrong_audience_rejected():
    with pytest.raises(IdTokenVerificationError):
        _verify(_encode(_claims(aud="a-different-client")))


def test_wrong_issuer_rejected():
    with pytest.raises(IdTokenVerificationError):
        _verify(_encode(_claims(iss="https://evil.example.com")))


def test_missing_sub_rejected():
    with pytest.raises(IdTokenVerificationError):
        _verify(_encode(_claims(sub=_DROP)))


def test_missing_exp_rejected():
    with pytest.raises(IdTokenVerificationError):
        _verify(_encode(_claims(exp=_DROP)))


# --- nonce (replay / token injection) --------------------------------------


def test_nonce_mismatch_rejected():
    with pytest.raises(IdTokenVerificationError):
        _verify(_encode(_claims(nonce="a-different-nonce")))


def test_missing_nonce_claim_rejected():
    with pytest.raises(IdTokenVerificationError):
        _verify(_encode(_claims(nonce=_DROP)))


# --- azp (authorized party) -------------------------------------------------


def test_multi_aud_without_azp_rejected():
    with pytest.raises(IdTokenVerificationError):
        _verify(_encode(_claims(aud=[AUDIENCE, "other-app"])))


def test_azp_mismatch_rejected():
    with pytest.raises(IdTokenVerificationError):
        _verify(_encode(_claims(azp="an-evil-client")))


# --- caller misconfiguration (programming errors → ValueError) --------------


def test_empty_algorithm_allowlist_is_value_error():
    with pytest.raises(ValueError):
        _verify(_encode(_claims()), algorithms=[])


def test_symmetric_algorithm_in_allowlist_refused():
    """Refuse to even run with an HMAC alg in the allowlist — that would reopen
    the confusion bypass. This is a ValueError (our misuse), not a rejected token."""
    with pytest.raises(ValueError):
        _verify(_encode(_claims()), algorithms=["HS256"])


def test_none_algorithm_in_allowlist_refused():
    with pytest.raises(ValueError):
        _verify(_encode(_claims()), algorithms=["none"])


def test_empty_nonce_is_value_error():
    with pytest.raises(ValueError):
        _verify(_encode(_claims()), nonce="")
