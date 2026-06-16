"""Unit tests for advanced-tool handoff token signing and claims.

These exercise ``create_advanced_tool_handoff_token`` directly without
hitting the API, so they're cheap to run and don't need a database.
The HTTP-level gating is covered separately in the endpoint tests.
"""

from __future__ import annotations

import time

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from datetime import timedelta

from app.core import security
from app.core.security import (
    ADVANCED_TOOL_AUDIENCE,
    ADVANCED_TOOL_HANDOFF_LIFETIME,
    UPLOAD_TOKEN_AUDIENCE,
    UPLOAD_TOKEN_LIFETIME,
    UPLOAD_TOKEN_SCOPE,
    UploadTokenError,
    create_advanced_tool_handoff_token,
    create_upload_token,
    verify_upload_token,
)


def _decode_unverified(token: str) -> dict:
    """Return the JWT payload without checking signature/audience.

    The tests assert specific claims; signature verification is exercised
    separately in the RS256 round-trip test.
    """
    return jwt.decode(token, options={"verify_signature": False})


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
def test_handoff_token_falls_back_to_hs256_without_private_key(monkeypatch):
    """OSS deployments shouldn't have to set up a keypair. With no
    private key configured, the token signs with HS256 keyed off
    ``SECRET_KEY`` so existing single-process deployments keep working."""
    monkeypatch.setattr(security.settings, "HANDOFF_SIGNING_PRIVATE_KEY_PEM", None)
    monkeypatch.setattr(security.settings, "HANDOFF_SIGNING_KEY_ID", None)

    token, _ = create_advanced_tool_handoff_token(
        user_id=1,
        guild_id=2,
        guild_role="admin",
        is_manager=True,
        can_create=True,
        scope="guild",
    )

    header = jwt.get_unverified_header(token)
    assert header["alg"] == "HS256"
    assert "kid" not in header


# ──────────────────────────────────────────────────────────────────────────
# Scoped upload tokens (SEC-12)
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_upload_token_round_trips_to_user_id():
    """A freshly minted upload token verifies back to the user it names."""
    token, seconds = create_upload_token(user_id=123)
    assert isinstance(token, str) and token.count(".") == 2
    assert seconds == int(UPLOAD_TOKEN_LIFETIME.total_seconds())
    assert verify_upload_token(token) == 123


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
    payload = jwt.decode(token, jwt_key, algorithms=[security.settings.ALGORITHM])
    assert payload["sub"] == "7"
    # ...and NOT under SECRET_KEY (proving the keys are actually decoupled).
    with pytest.raises(jwt.InvalidSignatureError):
        jwt.decode(
            token,
            security.settings.SECRET_KEY,
            algorithms=[security.settings.ALGORITHM],
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
