"""Unit tests for advanced-tool handoff token signing and claims.

These exercise ``create_advanced_tool_handoff_token`` directly without
hitting the API, so they're cheap to run and don't need a database.
The HTTP-level gating is covered separately in the endpoint tests.
"""

from __future__ import annotations

import base64
import json
import time
import uuid

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from datetime import timedelta

from app.core import security
from app.core.config import settings
from app.core.security import (
    ADVANCED_TOOL_AUDIENCE,
    ADVANCED_TOOL_HANDOFF_LIFETIME,
    AUTH_ACCESS_AUDIENCE,
    AUTH_TOKEN_ISSUER,
    HandoffSigningNotConfiguredError,
    JWT_ALGORITHM,
    UPLOAD_TOKEN_AUDIENCE,
    UPLOAD_TOKEN_LIFETIME,
    UPLOAD_TOKEN_SCOPE,
    UploadTokenError,
    create_access_token,
    create_advanced_tool_handoff_token,
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
def test_handoff_token_returns_token_and_lifetime_seconds():
    """The function returns ``(token, seconds)`` where seconds matches
    ``ADVANCED_TOOL_HANDOFF_LIFETIME`` so callers can populate
    ``expires_in_seconds`` without hardcoding a magic number."""
    token, seconds = create_advanced_tool_handoff_token(
        user_id=1,
        guild_id=2,
        guild_role="admin",
        is_manager=True,
        can_create=True,
        scope="guild",
    )

    assert isinstance(token, str) and token.count(".") == 2
    assert seconds == int(ADVANCED_TOOL_HANDOFF_LIFETIME.total_seconds())


@pytest.mark.unit
def test_handoff_token_jwt_exp_matches_advertised_seconds():
    """The JWT's ``exp`` claim must match the seconds returned to the
    caller — drift between the two would cause the embed's re-handoff
    schedule to disagree with when the token actually expires."""
    before = int(time.time())
    token, seconds = create_advanced_tool_handoff_token(
        user_id=1,
        guild_id=2,
        guild_role="admin",
        is_manager=True,
        can_create=True,
        scope="guild",
    )
    after = int(time.time())

    payload = _decode_unverified(token)
    # Allow ±1s for clock drift between time.time() calls
    expected_exp_low = before + seconds
    expected_exp_high = after + seconds
    assert expected_exp_low - 1 <= payload["exp"] <= expected_exp_high + 1


@pytest.mark.unit
def test_handoff_token_carries_required_claims():
    """All claims the embed depends on must be present and well-typed."""
    token, _ = create_advanced_tool_handoff_token(
        user_id=42,
        guild_id=7,
        initiative_id=99,
        guild_role="admin",
        is_manager=True,
        can_create=True,
        scope="initiative",
    )

    payload = _decode_unverified(token)
    assert payload["aud"] == ADVANCED_TOOL_AUDIENCE
    assert payload["iss"] == "initiative"
    assert payload["sub"] == "42"
    assert payload["guild_id"] == 7
    assert payload["initiative_id"] == 99
    assert payload["guild_role"] == "admin"
    assert payload["is_manager"] is True
    assert payload["can_create"] is True
    assert payload["scope"] == "initiative"
    assert payload["jti"] and isinstance(payload["jti"], str)


@pytest.mark.unit
def test_handoff_token_omits_initiative_id_at_guild_scope():
    """Guild-scoped tokens must not include an ``initiative_id`` claim;
    its absence is the marker that the embed should render the guild
    view, not an initiative one."""
    token, _ = create_advanced_tool_handoff_token(
        user_id=1,
        guild_id=2,
        guild_role="admin",
        is_manager=True,
        can_create=True,
        scope="guild",
    )

    payload = _decode_unverified(token)
    assert "initiative_id" not in payload
    assert payload["scope"] == "guild"


@pytest.mark.unit
def test_handoff_token_jti_is_unique_per_call():
    """Each mint must produce a fresh ``jti`` so the embed can blocklist
    a redeemed token without rejecting subsequent legitimate handoffs."""
    seen: set[str] = set()
    for _ in range(5):
        token, _ = create_advanced_tool_handoff_token(
            user_id=1,
            guild_id=2,
            guild_role="admin",
            is_manager=True,
            can_create=True,
            scope="guild",
        )
        payload = _decode_unverified(token)
        seen.add(payload["jti"])

    assert len(seen) == 5


@pytest.mark.unit
def test_handoff_token_signs_with_rs256_when_private_key_configured(monkeypatch):
    """When ``HANDOFF_SIGNING_PRIVATE_KEY_PEM`` is set, the token is
    signed with RS256 and carries the configured ``kid`` in its header.
    The matching public key verifies the signature end-to-end without
    sharing any secret."""
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("ascii")
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )

    monkeypatch.setattr(
        security.settings, "HANDOFF_SIGNING_PRIVATE_KEY_PEM", private_pem
    )
    monkeypatch.setattr(security.settings, "HANDOFF_SIGNING_KEY_ID", "test-rotation-1")

    token, _ = create_advanced_tool_handoff_token(
        user_id=1,
        guild_id=2,
        guild_role="admin",
        is_manager=True,
        can_create=True,
        scope="guild",
    )

    header = jwt.get_unverified_header(token)
    assert header["alg"] == "RS256"
    assert header["kid"] == "test-rotation-1"

    # Public-key verification — proves the embed can verify without ever
    # seeing FOSS's signing material.
    payload = jwt.decode(
        token,
        public_pem,
        algorithms=["RS256"],
        audience=ADVANCED_TOOL_AUDIENCE,
    )
    assert payload["scope"] == "guild"


@pytest.mark.unit
def test_handoff_token_refuses_to_mint_without_private_key(monkeypatch):
    """Handoff tokens are verified across a trust boundary, so there is no
    symmetric fallback: with no RS256 private key configured the mint fails
    closed rather than emit a token the embed can't verify by public key."""
    monkeypatch.setattr(security.settings, "HANDOFF_SIGNING_PRIVATE_KEY_PEM", None)
    monkeypatch.setattr(security.settings, "HANDOFF_SIGNING_KEY_ID", None)

    with pytest.raises(HandoffSigningNotConfiguredError):
        create_advanced_tool_handoff_token(
            user_id=1,
            guild_id=2,
            guild_role="admin",
            is_manager=True,
            can_create=True,
            scope="guild",
        )


@pytest.mark.unit
def test_handoff_token_always_signs_rs256_by_default():
    """With a key configured (the deployment default once ADVANCED_TOOL_URL is
    on), the token is RS256 — never a symmetric algorithm."""
    token, _ = create_advanced_tool_handoff_token(
        user_id=1,
        guild_id=2,
        guild_role="admin",
        is_manager=True,
        can_create=True,
        scope="guild",
    )

    header = jwt.get_unverified_header(token)
    assert header["alg"] == "RS256"


@pytest.mark.unit
def test_handoff_token_claim_tamper_fails_public_key_verification():
    """The embed authorizes off the signed ``guild_role`` claim. Flipping it
    (a member forging "admin") invalidates the RS256 signature, so public-key
    verification rejects the token — the claim can't be altered in transit
    without the private key, which the client never holds."""
    token, _ = create_advanced_tool_handoff_token(
        user_id=1,
        guild_id=2,
        initiative_id=5,
        guild_role="member",
        is_manager=False,
        can_create=False,
        scope="initiative",
    )
    public_pem = (
        serialization.load_pem_private_key(
            security.settings.HANDOFF_SIGNING_PRIVATE_KEY_PEM.encode("ascii"),
            password=None,
        )
        .public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )

    # Sanity: the untampered token verifies with the public key.
    assert (
        jwt.decode(
            token, public_pem, algorithms=["RS256"], audience=ADVANCED_TOOL_AUDIENCE
        )["guild_role"]
        == "member"
    )

    header_b64, payload_b64, sig_b64 = token.split(".")
    claims = json.loads(_b64url_decode(payload_b64))
    claims["guild_role"] = "admin"  # privilege-forgery attempt
    forged = f"{header_b64}.{_b64url_encode(json.dumps(claims).encode())}.{sig_b64}"

    with pytest.raises(jwt.InvalidSignatureError):
        jwt.decode(
            forged, public_pem, algorithms=["RS256"], audience=ADVANCED_TOOL_AUDIENCE
        )


@pytest.mark.unit
def test_billing_portal_handoff_carries_admin_claims_and_distinct_audience():
    """Claims present; audience distinct from the advanced-tool token."""
    token, seconds = security.create_billing_portal_handoff_token(
        user_id=42, guild_id=7, guild_role="admin"
    )
    assert seconds == int(ADVANCED_TOOL_HANDOFF_LIFETIME.total_seconds())
    assert jwt.get_unverified_header(token)["alg"] == "RS256"

    payload = _decode_unverified(token)
    assert payload["aud"] == security.BILLING_PORTAL_AUDIENCE
    assert payload["aud"] != ADVANCED_TOOL_AUDIENCE
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
    """A token signed with our secret but carrying a foreign audience (e.g. the
    advanced-tool handoff) must not be honored as an upload token."""
    handoff, _ = create_advanced_tool_handoff_token(
        user_id=1,
        guild_id=2,
        guild_role="admin",
        is_manager=True,
        can_create=True,
        scope="guild",
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
    handoff, _ = create_advanced_tool_handoff_token(
        user_id=7,
        guild_id=1,
        guild_role="admin",
        is_manager=True,
        can_create=True,
        scope="guild",
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
