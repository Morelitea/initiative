"""Unit tests for token signing and claims.

These exercise the minting functions directly without hitting the API, so
they're cheap to run and don't need a database. The HTTP-level gating is
covered separately in the endpoint tests.
"""

from __future__ import annotations

import base64
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
@pytest.mark.parametrize(
    ("stored_hash", "expected_match"),
    [
        (None, False),
        ("!", False),
        ("$argon2id$independent-fixture", True),
        ("$2b$12$independent-fixture", True),
    ],
)
def test_sign_in_password_check_runs_every_supported_kdf_step(
    monkeypatch, stored_hash: str | None, expected_match: bool
) -> None:
    """Account state selects a result, not how much KDF work is scheduled."""
    observed: list[tuple[str, str]] = []

    class FakeArgon2:
        def verify(self, hashed: str, plain: str) -> bool:
            assert plain == "candidate"
            observed.append(("argon2", hashed))
            return hashed == stored_hash

    def fake_bcrypt_check(plain: bytes, hashed: bytes) -> bool:
        assert plain == b"candidate"
        decoded = hashed.decode("utf-8")
        observed.append(("bcrypt", decoded))
        return decoded == stored_hash

    monkeypatch.setattr(security, "_argon2_hasher", FakeArgon2())
    monkeypatch.setattr(security.bcrypt, "checkpw", fake_bcrypt_check)

    assert security.verify_sign_in_password("candidate", stored_hash) is expected_match
    assert [scheme for scheme, _ in observed] == ["argon2", "bcrypt"]
    selected_hashes = [hashed for _, hashed in observed]
    if expected_match:
        assert stored_hash in selected_hashes
    else:
        assert stored_hash not in selected_hashes


@pytest.mark.unit
def test_sign_in_password_check_accepts_only_a_matching_account_hash() -> None:
    """Dummy work can never turn an absent or unusable credential into a login."""
    password = "independent-password-fixture"
    argon_hash = security.get_password_hash(password)
    bcrypt_hash = security.bcrypt.hashpw(
        password.encode("utf-8"), security.bcrypt.gensalt()
    ).decode("utf-8")

    assert security.verify_sign_in_password(password, argon_hash) is True
    assert security.verify_sign_in_password("wrong", argon_hash) is False
    assert security.verify_sign_in_password(password, bcrypt_hash) is True
    assert security.verify_sign_in_password("wrong", bcrypt_hash) is False
    assert security.verify_sign_in_password(password, None) is False
    assert security.verify_sign_in_password(password, "!") is False


@pytest.mark.unit
def test_billing_portal_handoff_carries_admin_claims_and_distinct_audience():
    """Claims present, and the audience is the portal's own."""
    token, seconds = security.create_billing_portal_handoff_token(
        guild_role="admin",
        user_ref="ubil_test42",
        guild_ref="gbil_test7",
    )
    assert seconds == int(BILLING_PORTAL_HANDOFF_LIFETIME.total_seconds())
    assert jwt.get_unverified_header(token)["alg"] == "RS256"

    payload = _decode_unverified(token)
    assert payload["aud"] == security.BILLING_PORTAL_AUDIENCE
    assert payload["iss"] == "initiative"
    assert payload["guild_role"] == "admin"
    assert payload["jti"] and isinstance(payload["jti"], str)
    # The two are named by reference and by nothing else — `sub` carries the
    # user's, and no row id of ours appears anywhere in the claims.
    assert payload["sub"] == "ubil_test42"
    assert payload["user_ref"] == "ubil_test42"
    assert payload["guild_ref"] == "gbil_test7"
    assert "guild_id" not in payload


@pytest.mark.unit
def test_billing_portal_handoff_refuses_to_mint_without_private_key(monkeypatch):
    """No RS256 key configured -> mint fails closed."""
    monkeypatch.setattr(security.settings, "HANDOFF_SIGNING_PRIVATE_KEY_PEM", None)
    with pytest.raises(HandoffSigningNotConfiguredError):
        security.create_billing_portal_handoff_token(
            guild_role="admin",
            user_ref="ubil_test1",
            guild_ref="gbil_test2",
        )


# ──────────────────────────────────────────────────────────────────────────
# Scoped upload tokens (SEC-12)
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_upload_token_round_trips_to_user_id():
    """A freshly minted upload token verifies back to the user it names,
    carrying its minting session's auth standing (empty by default)."""
    token, seconds = create_upload_token(user_id=123)
    assert isinstance(token, str) and token.count(".") == 2
    assert seconds == int(UPLOAD_TOKEN_LIFETIME.total_seconds())
    assert verify_upload_token(token) == (123, frozenset(), {}, frozenset())

    satisfied_token, _ = create_upload_token(
        user_id=123,
        satisfied_providers=[5, 2],
        satisfied_claims={"5": {"hd": ["acme.com"]}},
    )
    assert verify_upload_token(satisfied_token) == (
        123,
        frozenset({2, 5}),
        {"5": {"hd": ["acme.com"]}},
        frozenset(),
    )


@pytest.mark.unit
def test_upload_token_carries_how_the_session_was_opened():
    """A community can ask for a second factor or for a passkey, and the token
    carries the markers that answer each — a code presented after a password
    is not a key, so a rule asking for one is not answered by the other."""
    factor, _ = create_upload_token(user_id=7, session_amr={"mfa"})
    assert verify_upload_token(factor)[3] == frozenset({"mfa"})

    key, _ = create_upload_token(user_id=7, session_amr={"mfa", "hwk"})
    assert verify_upload_token(key)[3] == frozenset({"mfa", "hwk"})

    neither, _ = create_upload_token(user_id=7)
    assert verify_upload_token(neither)[3] == frozenset()


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
    session_jwt, _ = mint_access_token(
        subject="ucli_seven",
        token_version=1,
        session_id=uuid.uuid4(),
        amr=["pwd"],
        satisfied_providers=[],
    )
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

    token, _ = mint_access_token(
        subject="ucli_seven",
        token_version=1,
        session_id=uuid.uuid4(),
        amr=["pwd"],
        satisfied_providers=[],
    )
    # Verifies under the dedicated key...
    payload = jwt.decode(
        token,
        jwt_key,
        algorithms=[security.JWT_ALGORITHM],
        audience=AUTH_ACCESS_AUDIENCE,
        issuer=AUTH_TOKEN_ISSUER,
    )
    assert payload["sub"] == "ucli_seven"
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
        guild_role="admin",
        user_ref="ubil_test1",
        guild_ref="gbil_test2",
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
        subject="ucli_forty_two",
        token_version=3,
        session_id=sid,
        amr=["pwd", "otp"],
        satisfied_providers=[7, 9],
    )

    assert isinstance(token, str) and token.count(".") == 2
    assert seconds == settings.AUTH_ACCESS_TTL_MINUTES * 60

    payload = _decode_unverified(token)
    assert payload["sub"] == "ucli_forty_two"
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
        subject="ucli_one",
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
        subject="ucli_five",
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
    assert payload["sub"] == "ucli_five"


# ── Dual-verify decode (accepts new + legacy, rejects scoped) ───────────────


@pytest.mark.unit
def test_decode_session_token_accepts_new_access_token():
    token, _ = mint_access_token(
        subject="ucli_seven",
        token_version=2,
        session_id=uuid.uuid4(),
        amr=["pwd"],
        satisfied_providers=[3],
    )
    payload = decode_session_token(token)
    assert payload["sub"] == "ucli_seven"
    assert payload["ver"] == 2
    assert payload["aud"] == AUTH_ACCESS_AUDIENCE
    assert payload["sat"] == [3]


@pytest.mark.unit
def test_decode_session_token_refuses_the_pre_session_shape():
    """The JWT builds before 0.69.0 issued — signed by us, carrying ``sub`` and
    ``ver``, and no ``aud``/``iss`` — is no longer a session credential.

    Built here rather than minted, because nothing mints one any more. Its
    holder is not stranded: the refresh cookie is a separate credential and
    renewing it returns a token of the shape above."""
    legacy = jwt.encode(
        {
            "sub": "7",
            "ver": 2,
            "exp": datetime.now(timezone.utc) + timedelta(minutes=10),
        },
        settings.jwt_signing_key,
        algorithm=JWT_ALGORITHM,
    )
    with pytest.raises(jwt.PyJWTError):
        decode_session_token(legacy)


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
        guild_role="admin",
        user_ref="ubil_test7",
        guild_ref="gbil_test1",
    )
    with pytest.raises(jwt.PyJWTError):
        decode_session_token(handoff)


@pytest.mark.unit
def test_decode_session_token_rejects_expired_new_token():
    """An expired NEW token must surface its true ``ExpiredSignatureError`` from
    the first decode — not be masked by the legacy fallback's audience error —
    so cutover-window logs stay honest."""
    token, _ = mint_access_token(
        subject="ucli_seven",
        token_version=0,
        session_id=uuid.uuid4(),
        amr=["pwd"],
        satisfied_providers=[],
        expires_in=timedelta(seconds=-1),
    )
    with pytest.raises(jwt.ExpiredSignatureError):
        decode_session_token(token)


@pytest.mark.unit
def test_decode_session_token_rejects_garbage():
    with pytest.raises(jwt.PyJWTError):
        decode_session_token("not.a.jwt")


# ──────────────────────────────────────────────────────────────────────────
# Rotatable verifying keys
#
# The settings holding a peer's public key take concatenated PEM blocks, so
# both the old and the new key are trusted while that peer rotates. These
# cover the loader; the per-peer wiring is exercised beside each verifier.
# ──────────────────────────────────────────────────────────────────────────


DELEGATE_KID_SHAPE = "acme.auto-delegation-1"

_KEYPAIRS = [
    rsa.generate_private_key(public_exponent=65537, key_size=2048) for _ in range(3)
]


def private_pem(index: int) -> str:
    return (
        _KEYPAIRS[index]
        .private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
        .decode()
    )


def public_key(index: int):
    """One verifying key, as a caller that resolved it would hold it."""
    return _KEYPAIRS[index].public_key()


def public_bundle(*indexes: int) -> str:
    """A configured value trusting the given keypairs, in order."""
    return "".join(
        _KEYPAIRS[index]
        .public_key()
        .public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
        for index in indexes
    )


@pytest.mark.unit
def test_loader_reads_every_block_in_order():
    keys = security.load_verification_keys(public_bundle(0, 1, 2))
    assert len(keys) == 3
    assert [k.public_numbers().n for k in keys] == [
        _KEYPAIRS[i].public_key().public_numbers().n for i in (0, 1, 2)
    ]


@pytest.mark.unit
def test_loader_reads_a_single_block():
    """The ordinary one-key case is the same code path."""
    assert len(security.load_verification_keys(public_bundle(0))) == 1


@pytest.mark.unit
def test_loader_treats_empty_as_no_keys():
    """An unset setting is "no peer", not an error — callers decide what that
    means for them."""
    assert security.load_verification_keys("") == ()


@pytest.mark.unit
def test_loader_refuses_an_unreadable_block_rather_than_skipping_it():
    """A silently dropped block would leave a rotation looking configured
    while the key it added does nothing."""
    bundle = public_bundle(0) + "-----BEGIN PUBLIC KEY-----\nnope\n"
    with pytest.raises(security.PublicKeyBundleError) as excinfo:
        security.load_verification_keys(bundle)
    assert "block 2" in str(excinfo.value)


@pytest.mark.unit
def test_loader_refuses_a_private_key():
    """Only the public half belongs in a verifying setting."""
    with pytest.raises(security.PublicKeyBundleError):
        security.load_verification_keys(private_pem(0))


# --- delegation: which key a token is accepted under ------------------------

#: The shape a real ``sub`` has here: the pairwise subject the platform minted
#: for one member at one install, opaque to the app that holds it. These tests
#: are about key selection and carry it only so it can be read back out.
_SUBJECT = "mBqR7xK2wPL0vN4tZ8yC6sD1fG3hJ5nA"
#: The reference the delegate knows the guild by, as it would arrive.
_GUILD_REF = "gapp_wRkC8mBv1xQ2fTn6JhLpZs4dY7eA0uKq"


def _mint_delegation(
    *, signed_by: int, expires_in: int = 900, kid: str | None = None
) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "jti": uuid.uuid4().hex,
            "sub": _SUBJECT,
            "aud": settings.AUTO_DELEGATION_AUDIENCE,
            "iss": settings.AUTO_DELEGATION_ISSUER,
            "iat": int(now.timestamp()),
            "exp": now + timedelta(seconds=expires_in),
            "guild_ref": _GUILD_REF,
        },
        private_pem(signed_by),
        algorithm="RS256",
        headers={"kid": kid} if kid else None,
    )


@pytest.mark.unit
def test_delegation_accepts_the_key_it_was_given():
    claims = security.verify_auto_delegation_token(
        _mint_delegation(signed_by=0), keys=[public_key(0)]
    )
    assert (claims.subject, claims.guild_ref) == (_SUBJECT, _GUILD_REF)


@pytest.mark.unit
def test_delegation_accepts_either_key_while_the_delegate_rotates():
    """The point of passing a set: both keys work, so an app can publish its
    replacement and switch at its own pace rather than in one instant."""
    for index in (0, 1):
        assert (
            security.verify_auto_delegation_token(
                _mint_delegation(signed_by=index), keys=[public_key(0), public_key(1)]
            ).subject
            == _SUBJECT
        )


@pytest.mark.unit
def test_delegation_refuses_a_key_it_was_not_given():
    """Holding two keys is not holding every RS256 signer."""
    with pytest.raises(security.AutoDelegationVerificationError):
        security.verify_auto_delegation_token(
            _mint_delegation(signed_by=2), keys=[public_key(0), public_key(1)]
        )


@pytest.mark.unit
def test_delegation_refuses_when_nothing_resolved():
    """An empty set is the "no registration published this kid" case, and it
    answers the same way a bad signature does."""
    with pytest.raises(security.AutoDelegationVerificationError):
        security.verify_auto_delegation_token(_mint_delegation(signed_by=0), keys=[])


@pytest.mark.unit
def test_delegation_stops_accepting_a_dropped_key():
    """Rotation ends by dropping an entry, so that key must stop working."""
    with pytest.raises(security.AutoDelegationVerificationError):
        security.verify_auto_delegation_token(
            _mint_delegation(signed_by=0), keys=[public_key(1)]
        )


@pytest.mark.unit
def test_a_token_key_id_does_not_steer_verification():
    """The ``kid`` selects which registration's keys are tried; within them it
    decides nothing. A token stamped with a misleading one still stands or
    falls on the key that actually signed it."""
    assert (
        security.verify_auto_delegation_token(
            _mint_delegation(signed_by=1, kid="names-the-other-key"),
            keys=[public_key(0), public_key(1)],
        ).subject
        == _SUBJECT
    )
    with pytest.raises(security.AutoDelegationVerificationError):
        security.verify_auto_delegation_token(
            _mint_delegation(signed_by=2, kid=DELEGATE_KID_SHAPE),
            keys=[public_key(0), public_key(1)],
        )


@pytest.mark.unit
def test_delegation_reports_expiry_rather_than_the_next_key():
    """With several keys tried, the reported failure is the real one."""
    with pytest.raises(security.AutoDelegationVerificationError) as excinfo:
        security.verify_auto_delegation_token(
            _mint_delegation(signed_by=0, expires_in=-30),
            keys=[public_key(0), public_key(1)],
        )
    assert "expired" in str(excinfo.value).lower()


@pytest.mark.unit
def test_delegation_is_off_where_no_app_platform_is_configured(monkeypatch):
    monkeypatch.setattr(security.settings, "APP_PLATFORM_SIGNING_PRIVATE_KEY_PEM", None)
    assert security.delegation_possible() is False


def test_the_sign_in_dummy_bcrypt_cost_is_pinned_not_inherited() -> None:
    """The dummy's cost decides what an unknown address costs to probe.

    `verify_sign_in_password` pays a bcrypt check for every sign-in so that an
    address with no account costs the same as one with a legacy bcrypt account.
    That equality holds only while the dummy's cost matches the stored hashes'.

    Measured on this machine, the gap between adjacent costs is not subtle:
    cost 10 verifies in ~102 ms and cost 12 in ~400 ms. So if the dummy took
    whatever `bcrypt.gensalt()` currently defaults to, a library release that
    moved the default would re-open the difference for every legacy account at
    once, silently, on upgrade.

    Pinning it keeps that a deliberate edit. The constant is the contract.
    """
    stored = security._SIGN_IN_DUMMY_BCRYPT_HASH
    text = stored.decode() if isinstance(stored, bytes) else stored
    cost = int(text.split("$")[2])

    assert cost == security.SIGN_IN_BCRYPT_COST


def test_has_usable_password_reads_the_hash_not_the_null():
    """The definition of "no usable password": a value outside the schemes
    ``verify_password`` checks, whatever it is."""
    from app.core.security import get_password_hash, has_usable_password

    assert has_usable_password(get_password_hash("something")) is True
    # NULL, and the marker a 0152 downgrade writes, read the same.
    assert has_usable_password(None) is False
    assert has_usable_password("!") is False
    assert has_usable_password("") is False
    assert has_usable_password("not-a-hash") is False
    # A legacy bcrypt hash is still one we can check.
    assert has_usable_password("$2b$12$" + "x" * 53) is True
