"""Integration tests for auto-delegation hardening.

These exercise the security properties the auth dep enforces on delegation
JWTs minted by initiative-auto:

* signature, audience, issuer (negative tests against tampered tokens)
* one-shot replay rejection via the jti blocklist
* guild_id JWT claim must match the X-Guild-ID request header when both
  are present
* deactivated users can't be impersonated even with a valid token

These don't repeat the unit tests on token issuance — those live next
to ``create_advanced_tool_handoff_token``. Here the focus is on the
verification + blocklist + cross-claim consistency the dep enforces.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core import config as config_module
from app.models.user import UserStatus
from app.testing.factories import create_user


# A fresh keypair per test session — keeps signatures from leaking between
# tests if the same private key were reused via fixture caching.
_keypair = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_PRIVATE_PEM = _keypair.private_bytes(
    serialization.Encoding.PEM,
    serialization.PrivateFormat.PKCS8,
    serialization.NoEncryption(),
).decode()
_PUBLIC_PEM = _keypair.public_key().public_bytes(
    serialization.Encoding.PEM,
    serialization.PublicFormat.SubjectPublicKeyInfo,
).decode()


def _mint_delegation(
    *,
    user_id: int,
    guild_id: int,
    initiative_id: int | None = None,
    jti: str | None = None,
    aud: str = "initiative:auto-delegation",
    iss: str = "initiative-auto",
    private_pem: str = _PRIVATE_PEM,
    expires_in: int = 900,
) -> str:
    now = datetime.now(timezone.utc)
    payload: dict = {
        "jti": jti or secrets.token_hex(8),
        "sub": str(user_id),
        "aud": aud,
        "iss": iss,
        "iat": int(now.timestamp()),
        "exp": now + timedelta(seconds=expires_in),
        "guild_id": guild_id,
    }
    if initiative_id is not None:
        payload["initiative_id"] = initiative_id
    return jwt.encode(payload, private_pem, algorithm="RS256")


@pytest.fixture(autouse=True)
def _enable_delegation(monkeypatch):
    """Configure the public key for the duration of each test in this file.
    Without it, ``_authenticate_auto_delegation`` short-circuits to None
    and the tests fall through to standard-JWT auth, which is not what
    we're exercising here."""
    monkeypatch.setattr(config_module.settings, "AUTO_DELEGATION_PUBLIC_KEY_PEM", _PUBLIC_PEM)


@pytest.mark.integration
async def test_delegation_token_is_one_shot(client: AsyncClient, session: AsyncSession):
    """The same jti must succeed once and fail on the second presentation,
    regardless of the JWT's remaining lifetime. Without this, a 15-minute
    token captured in transit can be replayed indefinitely."""
    user = await create_user(session, email="user@example.com")
    token = _mint_delegation(user_id=user.id, guild_id=1, jti="replay-target-001")

    first = await client.get(
        "/api/v1/users/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert first.status_code == 200, first.text

    second = await client.get(
        "/api/v1/users/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    # Replay falls through past delegation auth, then through the
    # standard JWT path which rejects an HS256-shaped token, ending
    # with the standard 401.
    assert second.status_code == 401


@pytest.mark.integration
async def test_delegation_rejects_guild_mismatch(
    client: AsyncClient, session: AsyncSession
):
    """A token issued for guild 42 must not authenticate a request that
    sets X-Guild-ID: 99 — even if the user is a member of both. Stops
    cross-guild lateral movement using a single delegation."""
    user = await create_user(session, email="cross-guild@example.com")
    token = _mint_delegation(user_id=user.id, guild_id=42)

    response = await client.get(
        "/api/v1/users/me",
        headers={
            "Authorization": f"Bearer {token}",
            "X-Guild-ID": "99",
        },
    )
    assert response.status_code == 401


@pytest.mark.integration
async def test_delegation_allows_matching_guild_header(
    client: AsyncClient, session: AsyncSession
):
    """The header check is permissive when JWT.guild_id == X-Guild-ID —
    the typical happy path with a guild-scoped endpoint."""
    user = await create_user(session, email="happy-path@example.com")
    token = _mint_delegation(user_id=user.id, guild_id=42)

    response = await client.get(
        "/api/v1/users/me",
        headers={
            "Authorization": f"Bearer {token}",
            "X-Guild-ID": "42",
        },
    )
    assert response.status_code == 200


@pytest.mark.integration
async def test_delegation_allows_missing_guild_header(
    client: AsyncClient, session: AsyncSession
):
    """``/users/me`` is cross-guild; no X-Guild-ID required. The guild
    consistency check must allow the call when the header is absent."""
    user = await create_user(session, email="cross-guild-allowed@example.com")
    token = _mint_delegation(user_id=user.id, guild_id=42)

    response = await client.get(
        "/api/v1/users/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200


@pytest.mark.integration
async def test_delegation_rejects_deactivated_user(
    client: AsyncClient, session: AsyncSession
):
    """Workflows owned by deactivated users must stop working
    immediately — no grace period during which their old tokens still
    function."""
    user = await create_user(session, email="deactivated@example.com")
    user.status = UserStatus.deactivated
    session.add(user)
    await session.commit()
    await session.refresh(user)

    token = _mint_delegation(user_id=user.id, guild_id=1)

    response = await client.get(
        "/api/v1/users/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 401


@pytest.mark.integration
async def test_delegation_rejects_unknown_user(
    client: AsyncClient, session: AsyncSession
):
    """A delegation for a user_id that doesn't exist in the DB must
    fail — auto can't manufacture user identities Initiative didn't
    issue."""
    token = _mint_delegation(user_id=9_999_999, guild_id=1)

    response = await client.get(
        "/api/v1/users/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 401


@pytest.mark.integration
async def test_delegation_rejects_wrong_audience(
    client: AsyncClient, session: AsyncSession
):
    """A token with a different audience claim must not authenticate.
    Stops a regular session JWT (or any other audience) from being
    re-presented as a delegation."""
    user = await create_user(session, email="wrong-aud@example.com")
    token = _mint_delegation(user_id=user.id, guild_id=1, aud="initiative:something-else")

    response = await client.get(
        "/api/v1/users/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 401


@pytest.mark.integration
async def test_delegation_rejects_wrong_issuer(
    client: AsyncClient, session: AsyncSession
):
    """Issuer must match — defense in depth alongside the audience check."""
    user = await create_user(session, email="wrong-iss@example.com")
    token = _mint_delegation(user_id=user.id, guild_id=1, iss="someone-else")

    response = await client.get(
        "/api/v1/users/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 401


@pytest.mark.integration
async def test_delegation_rejects_signature_from_other_key(
    client: AsyncClient, session: AsyncSession
):
    """A token signed with a different RSA key must fail signature
    verification — the load-bearing crypto property of the whole flow."""
    user = await create_user(session, email="bad-sig@example.com")
    other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    other_private = other_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    token = _mint_delegation(user_id=user.id, guild_id=1, private_pem=other_private)

    response = await client.get(
        "/api/v1/users/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 401


@pytest.mark.integration
async def test_delegation_disabled_when_public_key_unset(
    client: AsyncClient, session: AsyncSession, monkeypatch
):
    """Operator hasn't configured the public key → delegation auth is
    fully off and the request falls through to the standard 401 from
    the JWT path. No 500 from a half-configured state."""
    monkeypatch.setattr(config_module.settings, "AUTO_DELEGATION_PUBLIC_KEY_PEM", None)

    user = await create_user(session, email="delegation-off@example.com")
    token = _mint_delegation(user_id=user.id, guild_id=1)

    response = await client.get(
        "/api/v1/users/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 401
