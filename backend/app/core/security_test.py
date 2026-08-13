"""Unit tests for token signing and claims.

These exercise the minting functions directly without hitting the API, so
they're cheap to run and don't need a database. The HTTP-level gating is
covered separately in the endpoint tests.
"""

from __future__ import annotations

import base64
import json
import uuid

import jwt
import pytest

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from datetime import datetime, timedelta, timezone

from app.core import security
from app.core.config import settings
from app.core.security import (
    AUTH_ACCESS_AUDIENCE,
    AUTH_TOKEN_ISSUER,
    BILLING_PORTAL_HANDOFF_LIFETIME,
    HandoffSigningNotConfiguredError,
    JWT_ALGORITHM,
    UPLOAD_TOKEN_AUDIENCE,
    UPLOAD_TOKEN_LIFETIME,
    UPLOAD_TOKEN_SCOPE,
    UploadTokenError,
    create_access_token,
    create_upload_token,
    decode_session_token,
    mint_access_token,
    verify_upload_token,
)


def _decode_unverified(token: str) -> dict:
    """Return the JWT payload without checking signature/audience.

    The tests assert specific claims; signature verification is exercised
    separately in the RS256 round-trip test.
    """
    return jwt.decode(token, options={"verify_signature": False})


def _b64url_decode(seg: str) -> bytes:
    return base64.urlsafe_b64decode(seg + "=" * (-len(seg) % 4))


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


@pytest.mark.unit
def test_billing_portal_handoff_carries_admin_claims_and_distinct_audience():
    """Claims present, and the audience is the portal's own."""
    token, seconds = security.create_billing_portal_handoff_token(
        user_id=42, guild_id=7, guild_role="admin"
    )
    assert seconds == int(BILLING_PORTAL_HANDOFF_LIFETIME.total_seconds())
    assert jwt.get_unverified_header(token)["alg"] == "RS256"

    payload = _decode_unverified(token)
    assert payload["aud"] == security.BILLING_PORTAL_AUDIENCE
    assert payload["iss"] == "initiative"
    assert payload["sub"] == "42"
    assert payload["guild_id"] == 7
    assert payload["guild_role"] == "admin"
    assert payload["jti"] and isinstance(payload["jti"], str)


@pytest.mark.unit
def test_billing_portal_handoff_refuses_to_mint_without_private_key(monkeypatch):
    """No RS256 key configured -> mint fails closed."""
    monkeypatch.setattr(security.settings, "HANDOFF_SIGNING_PRIVATE_KEY_PEM", None)
    with pytest.raises(HandoffSigningNotConfiguredError):
        security.create_billing_portal_handoff_token(
            user_id=1, guild_id=2, guild_role="admin"
        )


# ──────────────────────────────────────────────────────────────────────────
# Scoped upload tokens (SEC-12)
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_upload_token_round_trips_to_user_id():
    """A freshly minted upload token verifies back to the user it names,
    carrying its minting session's satisfied-provider set (empty by default)."""
    token, seconds = create_upload_token(user_id=123)
    assert isinstance(token, str) and token.count(".") == 2
    assert seconds == int(UPLOAD_TOKEN_LIFETIME.total_seconds())
    assert verify_upload_token(token) == (123, frozenset())

    satisfied_token, _ = create_upload_token(user_id=123, satisfied_providers=[5, 2])
    assert verify_upload_token(satisfied_token) == (123, frozenset({2, 5}))


@pytest.mark.unit
def test_upload_token_carries_scope_and_audience_but_no_ver():
    """The token must carry the uploads aud/scope and deliberately omit
    ``ver`` — the general session-JWT path keys on ``ver`` and so will
    reject this token as an API credential."""
    token, _ = create_upload_token(user_id=7)
    payload = _decode_unverified(token)
    assert payload["aud"] == UPLOAD_TOKEN_AUDIENCE
    assert payload["scope"] == UPLOAD_TOKEN_SCOPE
    assert payload["sub"] == "7"
    assert "ver" not in payload


@pytest.mark.unit
def test_verify_upload_token_rejects_session_jwt():
    """A normal session JWT (different shape, no uploads aud) must not pass
    upload-token verification."""
    session_jwt = security.create_access_token(subject="7", token_version=1)
    with pytest.raises(UploadTokenError):
        verify_upload_token(session_jwt)


@pytest.mark.unit
def test_verify_upload_token_rejects_expired_token():
    """An expired upload token is rejected."""
    token, _ = create_upload_token(user_id=7, expires_in=timedelta(seconds=-1))
    with pytest.raises(UploadTokenError):
        verify_upload_token(token)


@pytest.mark.unit
def test_session_jwt_signed_with_dedicated_jwt_signing_key(monkeypatch):
    """When JWT_SIGNING_KEY is set, session JWTs are signed/verified with it — so it
    can be rotated independently of the encryption-rooting SECRET_KEY."""
    jwt_key = "j" * 48
    monkeypatch.setattr(security.settings, "JWT_SIGNING_KEY", jwt_key)

    token = security.create_access_token(subject="7", token_version=1)
    # Verifies under the dedicated key...
    payload = jwt.decode(token, jwt_key, algorithms=[security.JWT_ALGORITHM])
    assert payload["sub"] == "7"
    # ...and NOT under SECRET_KEY (proving the keys are actually decoupled).
    with pytest.raises(jwt.InvalidSignatureError):
        jwt.decode(
            token,
            security.settings.SECRET_KEY,
            algorithms=[security.JWT_ALGORITHM],
        )


@pytest.mark.unit
def test_jwt_signing_key_does_not_affect_encryption(monkeypatch):
    """Setting/rotating JWT_SIGNING_KEY must not change encryption or the email HMAC —
    those are rooted in SECRET_KEY alone, so a JWT rotation can't orphan data."""
    from app.core.encryption import SALT_EMAIL, encrypt_field, hash_email

    before_ct = encrypt_field("alice@example.com", SALT_EMAIL)
    before_hash = hash_email("alice@example.com")

    monkeypatch.setattr(security.settings, "JWT_SIGNING_KEY", "j" * 48)

    # Same email hash, and the pre-rotation ciphertext still decrypts.
    from app.core.encryption import decrypt_field

    assert hash_email("alice@example.com") == before_hash
    assert decrypt_field(before_ct, SALT_EMAIL) == "alice@example.com"


@pytest.mark.unit
def test_verify_upload_token_rejects_wrong_audience():
    """A token signed with our secret but carrying a foreign audience (e.g. a
    handoff into another service) must not be honored as an upload token."""
    handoff, _ = security.create_billing_portal_handoff_token(
        user_id=1, guild_id=2, guild_role="admin"
    )
    with pytest.raises(UploadTokenError):
        verify_upload_token(handoff)


# ── New-model access token (auth rewrite, Phase 0) ─────────────────────────


@pytest.mark.unit
def test_mint_access_token_carries_session_claims():
    """The access token names the user, the backing session, and the auth
    context (amr/sat) that the guild-policy gate reads locally."""
    sid = uuid.uuid4()
    token, seconds = mint_access_token(
        user_id=42,
        token_version=3,
        session_id=sid,
        amr=["pwd", "otp"],
        satisfied_providers=[7, 9],
    )

    assert isinstance(token, str) and token.count(".") == 2
    assert seconds == settings.AUTH_ACCESS_TTL_MINUTES * 60

    payload = _decode_unverified(token)
    assert payload["sub"] == "42"
    assert payload["sid"] == str(sid)
    assert payload["ver"] == 3
    assert payload["amr"] == ["pwd", "otp"]
    assert payload["sat"] == [7, 9]
    assert payload["iss"] == AUTH_TOKEN_ISSUER
    assert payload["aud"] == AUTH_ACCESS_AUDIENCE


@pytest.mark.unit
def test_mint_access_token_exp_matches_advertised_seconds():
    """``exp`` must equal ``iat`` + the returned seconds — the SPA schedules its
    refresh off that number, so drift would refresh late (or never)."""
    sid = uuid.uuid4()
    token, seconds = mint_access_token(
        user_id=1,
        token_version=0,
        session_id=sid,
        amr=["pwd"],
        satisfied_providers=[],
    )

    payload = _decode_unverified(token)
    assert payload["exp"] - payload["iat"] == seconds


@pytest.mark.unit
def test_mint_access_token_is_verifiable_with_expected_audience():
    """A round-trip decode with the audience the verification path will require
    must succeed — signature + aud + iss all line up."""
    sid = uuid.uuid4()
    token, _ = mint_access_token(
        user_id=5,
        token_version=1,
        session_id=sid,
        amr=["pwd"],
        satisfied_providers=[],
    )

    payload = jwt.decode(
        token,
        settings.jwt_signing_key,
        algorithms=[JWT_ALGORITHM],
        audience=AUTH_ACCESS_AUDIENCE,
        issuer=AUTH_TOKEN_ISSUER,
        options={"require": ["exp", "iat", "sub", "sid", "aud", "iss"]},
    )
    assert payload["sub"] == "5"


# ── Dual-verify decode (accepts new + legacy, rejects scoped) ───────────────


@pytest.mark.unit
def test_decode_session_token_accepts_new_access_token():
    token, _ = mint_access_token(
        user_id=7,
        token_version=2,
        session_id=uuid.uuid4(),
        amr=["pwd"],
        satisfied_providers=[3],
    )
    payload = decode_session_token(token)
    assert payload["sub"] == "7"
    assert payload["ver"] == 2
    assert payload["aud"] == AUTH_ACCESS_AUDIENCE
    assert payload["sat"] == [3]


@pytest.mark.unit
def test_decode_session_token_accepts_legacy_token():
    """The legacy session JWT (no aud/iss) must keep validating across the
    cutover window."""
    token = create_access_token(subject="7", token_version=2)
    payload = decode_session_token(token)
    assert payload["sub"] == "7"
    assert payload["ver"] == 2
    assert "aud" not in payload


@pytest.mark.unit
def test_decode_session_token_rejects_scoped_upload_token():
    """A scoped upload token carries a foreign aud — it must NOT be honored as
    a session credential on either decode path (the key security property)."""
    upload, _ = create_upload_token(user_id=7)
    with pytest.raises(jwt.PyJWTError):
        decode_session_token(upload)


@pytest.mark.unit
def test_decode_session_token_rejects_handoff_token():
    handoff, _ = security.create_billing_portal_handoff_token(
        user_id=7, guild_id=1, guild_role="admin"
    )
    with pytest.raises(jwt.PyJWTError):
        decode_session_token(handoff)


@pytest.mark.unit
def test_decode_session_token_rejects_expired_new_token():
    """An expired NEW token must surface its true ``ExpiredSignatureError`` from
    the first decode — not be masked by the legacy fallback's audience error —
    so cutover-window logs stay honest."""
    token, _ = mint_access_token(
        user_id=7,
        token_version=0,
        session_id=uuid.uuid4(),
        amr=["pwd"],
        satisfied_providers=[],
        expires_in=timedelta(seconds=-1),
    )
    with pytest.raises(jwt.ExpiredSignatureError):
        decode_session_token(token)


@pytest.mark.unit
def test_decode_session_token_rejects_expired_legacy_token():
    """An expired LEGACY token also surfaces ``ExpiredSignatureError`` (via the
    fallback decode), not a misleading audience error."""
    token = create_access_token(
        subject="7", token_version=0, expires_delta=timedelta(seconds=-1)
    )
    with pytest.raises(jwt.ExpiredSignatureError):
        decode_session_token(token)


@pytest.mark.unit
def test_decode_session_token_rejects_garbage():
    with pytest.raises(jwt.PyJWTError):
        decode_session_token("not.a.jwt")


# ──────────────────────────────────────────────────────────────────────────
# Inbound delegation: verifying against a key set
#
# The delegate rotates by having both keys trusted for a release, so these
# cover which key a token resolves to and what a bad key set does.
# ──────────────────────────────────────────────────────────────────────────


_DELEGATION_KEYPAIRS = [
    rsa.generate_private_key(public_exponent=65537, key_size=2048) for _ in range(3)
]


def _delegation_private_pem(index: int) -> str:
    return (
        _DELEGATION_KEYPAIRS[index]
        .private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
        .decode()
    )


def _delegation_public_pem(index: int) -> str:
    return (
        _DELEGATION_KEYPAIRS[index]
        .public_key()
        .public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )


def _delegation_jwks(*pairs: tuple[str, int], **overrides) -> str:
    """A JWKS document naming the given ``(kid, keypair index)`` keys."""
    keys = []
    for kid, index in pairs:
        numbers = _DELEGATION_KEYPAIRS[index].public_key().public_numbers()
        entry = {
            "kty": "RSA",
            "use": "sig",
            "alg": "RS256",
            "kid": kid,
            "n": _b64url_encode(
                numbers.n.to_bytes((numbers.n.bit_length() + 7) // 8, "big")
            ),
            "e": _b64url_encode(
                numbers.e.to_bytes((numbers.e.bit_length() + 7) // 8, "big")
            ),
        }
        entry.update(overrides)
        keys.append(entry)
    return json.dumps({"keys": keys})


def _mint_delegation(
    *,
    signed_by: int,
    kid: str | None = None,
    expires_in: int = 900,
    user_id: int = 5,
    guild_id: int = 9,
) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "jti": uuid.uuid4().hex,
            "sub": str(user_id),
            "aud": settings.AUTO_DELEGATION_AUDIENCE,
            "iss": settings.AUTO_DELEGATION_ISSUER,
            "iat": int(now.timestamp()),
            "exp": now + timedelta(seconds=expires_in),
            "guild_id": guild_id,
        },
        _delegation_private_pem(signed_by),
        algorithm="RS256",
        headers={"kid": kid} if kid else None,
    )


@pytest.fixture
def delegation_keys(monkeypatch):
    """Configure the delegation trust for one test, key set and/or PEM."""

    def configure(*, key_set: str | None = None, pem: str | None = None):
        monkeypatch.setattr(security.settings, "AUTO_DELEGATION_PUBLIC_KEYS", key_set)
        monkeypatch.setattr(security.settings, "AUTO_DELEGATION_PUBLIC_KEY_PEM", pem)

    return configure


@pytest.mark.unit
def test_delegation_verifies_against_the_key_the_kid_names(delegation_keys):
    """Both keys trusted at once — a token signed with either resolves."""
    delegation_keys(key_set=_delegation_jwks(("2026-01", 0), ("2026-07", 1)))

    for kid, index in (("2026-01", 0), ("2026-07", 1)):
        claims = security.verify_auto_delegation_token(
            _mint_delegation(signed_by=index, kid=kid)
        )
        assert claims.user_id == 5
        assert claims.guild_id == 9


@pytest.mark.unit
def test_delegation_verifies_a_trusted_key_under_an_unknown_kid(delegation_keys):
    """The id orders the search, it does not decide it: a token whose ``kid``
    matches nothing still verifies against a configured key. That is what lets
    the two sides roll out a rotation independently."""
    delegation_keys(key_set=_delegation_jwks(("2026-01", 0), ("2026-07", 1)))

    claims = security.verify_auto_delegation_token(
        _mint_delegation(signed_by=1, kid="an-id-this-side-has-not-heard-of")
    )
    assert claims.user_id == 5


@pytest.mark.unit
def test_delegation_refuses_a_key_that_is_not_configured(delegation_keys):
    """Trusting a set is not trusting anything RS256: the third keypair was
    never configured."""
    delegation_keys(key_set=_delegation_jwks(("2026-01", 0), ("2026-07", 1)))

    with pytest.raises(security.AutoDelegationVerificationError):
        security.verify_auto_delegation_token(
            _mint_delegation(signed_by=2, kid="2026-07")
        )


@pytest.mark.unit
def test_single_pem_still_accepts_a_token_stamped_with_a_kid(delegation_keys):
    """The pre-existing single-key form keeps working once the delegate starts
    stamping ids — the PEM names none, so it is tried whatever arrives."""
    delegation_keys(pem=_delegation_public_pem(0))

    claims = security.verify_auto_delegation_token(
        _mint_delegation(signed_by=0, kid="2026-07")
    )
    assert claims.user_id == 5


@pytest.mark.unit
def test_both_forms_together_accept_either_key(delegation_keys):
    """The migration state: the old PEM and the new set configured at once."""
    delegation_keys(
        key_set=_delegation_jwks(("2026-07", 1)), pem=_delegation_public_pem(0)
    )

    assert security.verify_auto_delegation_token(_mint_delegation(signed_by=0)).user_id
    assert security.verify_auto_delegation_token(
        _mint_delegation(signed_by=1, kid="2026-07")
    ).user_id


@pytest.mark.unit
def test_expired_token_reports_expiry_rather_than_the_next_key(delegation_keys):
    """With several keys tried, the failure reported is the one from the key
    the token named — not a signature error from an unrelated key."""
    delegation_keys(key_set=_delegation_jwks(("2026-01", 0), ("2026-07", 1)))

    with pytest.raises(security.AutoDelegationVerificationError) as excinfo:
        security.verify_auto_delegation_token(
            _mint_delegation(signed_by=1, kid="2026-07", expires_in=-30)
        )
    assert "expired" in str(excinfo.value).lower()


@pytest.mark.unit
def test_delegation_is_unconfigured_when_neither_form_is_set(delegation_keys):
    delegation_keys()

    assert security.auto_delegation_configured() is False
    with pytest.raises(security.AutoDelegationVerificationError):
        security.verify_auto_delegation_token(_mint_delegation(signed_by=0))


@pytest.mark.unit
@pytest.mark.parametrize("form", ["pem", "key_set"])
def test_either_form_alone_counts_as_configured(delegation_keys, form):
    """Delegate-owned surfaces key off this, so a deployment that configured
    only the set must not read as having no delegate."""
    if form == "pem":
        delegation_keys(pem=_delegation_public_pem(0))
    else:
        delegation_keys(key_set=_delegation_jwks(("2026-01", 0)))

    assert security.auto_delegation_configured() is True


@pytest.mark.unit
@pytest.mark.parametrize(
    "key_set",
    ["{not json", '{"keys": []}', '{"keys": [{"kid": "a"}]}'],
)
def test_unreadable_key_set_is_reported_as_configuration(delegation_keys, key_set):
    """A document that yields no usable key raises rather than resolving to an
    empty trust set, so the mistake reads as configuration."""
    delegation_keys(key_set=key_set)

    with pytest.raises(security.AutoDelegationVerificationError) as excinfo:
        security.verify_auto_delegation_token(_mint_delegation(signed_by=0))
    assert "not a usable key set" in str(excinfo.value)


@pytest.mark.unit
def test_key_set_ignores_a_key_of_the_wrong_algorithm(delegation_keys):
    """An RS512 entry alongside a good one does not make its token verify."""
    delegation_keys(
        key_set=_delegation_jwks(("2026-01", 0), alg="RS512"),
    )

    with pytest.raises(security.AutoDelegationVerificationError):
        security.verify_auto_delegation_token(
            _mint_delegation(signed_by=0, kid="2026-01")
        )
