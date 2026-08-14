"""Delegation verified against the signing app's own registration.

The companion file to ``auto_delegation_test.py``, which covers the same auth
dep reading the deployment-wide key. Here the token names a ``kid``, and what
decides it is the registration that published that key: it must be enabled and
hold the ``delegation`` grant, so an operator ends an app's ability to act with
an edit rather than a key rotation.
"""

from __future__ import annotations

import json
import secrets
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import AsyncClient
from jwt.algorithms import RSAAlgorithm
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core import config as config_module
from app.models.platform.app_service_registration import (
    AppServiceRegistration,
    AppServiceStatus,
)
from app.services.marketplace.registration_lookup import (
    delegate_available,
    invalidate_registrations,
)
from app.testing import create_user

PUBLIC_ID = "acme.auto"
KID = f"{PUBLIC_ID}-delegation-1"

_keypair = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_PRIVATE_PEM = _keypair.private_bytes(
    serialization.Encoding.PEM,
    serialization.PrivateFormat.PKCS8,
    serialization.NoEncryption(),
).decode()


def _jwks(kid: str = KID) -> dict:
    entry = json.loads(RSAAlgorithm.to_jwk(_keypair.public_key()))
    entry["kid"] = kid
    return {"keys": [entry]}


def _mint(*, user_id: int, guild_id: int, kid: str | None = KID) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "jti": secrets.token_hex(8),
            "sub": str(user_id),
            "aud": "initiative:auto-delegation",
            "iss": "initiative-auto",
            "iat": int(now.timestamp()),
            "exp": now + timedelta(seconds=900),
            "guild_id": guild_id,
        },
        _PRIVATE_PEM,
        algorithm="RS256",
        headers={"kid": kid} if kid else None,
    )


@pytest.fixture(autouse=True)
def _registration_is_the_only_trust_root(monkeypatch):
    """No deployment-wide key: what verifies a token here is the registration.

    The app-platform signing key stands in for "registrations are reachable on
    this deployment", which is what the cheap gate in the auth dep reads.
    """
    monkeypatch.setattr(config_module.settings, "AUTO_DELEGATION_PUBLIC_KEY_PEM", None)
    monkeypatch.setattr(
        config_module.settings,
        "APP_PLATFORM_SIGNING_PRIVATE_KEY_PEM",
        "-----BEGIN PRIVATE KEY-----",
    )
    invalidate_registrations()
    yield
    invalidate_registrations()


async def _register(
    session: AsyncSession,
    *,
    grants: list[str],
    enabled: bool = True,
    key_set: dict | None = None,
) -> AppServiceRegistration:
    row = AppServiceRegistration(
        public_id=PUBLIC_ID,
        base_url="http://auto:8080",
        allowed_origins=["http://auto:8080"],
        secret_encrypted=None,
        grants=grants,
        delegation_jwks=_jwks() if key_set is None else key_set,
        enabled=enabled,
        status=AppServiceStatus.OK,
    )
    session.add(row)
    await session.commit()
    invalidate_registrations()
    return row


@pytest.mark.integration
async def test_a_granted_registration_verifies_the_token(
    client: AsyncClient, session: AsyncSession
):
    user = await create_user(session, email="delegated@example.com")
    await _register(session, grants=["delegation"])

    response = await client.get(
        "/api/v1/users/me",
        headers={"Authorization": f"Bearer {_mint(user_id=user.id, guild_id=1)}"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["email"] == "delegated@example.com"


@pytest.mark.integration
async def test_the_kill_switch_ends_delegation(
    client: AsyncClient, session: AsyncSession
):
    user = await create_user(session, email="switched-off@example.com")
    await _register(session, grants=["delegation"], enabled=False)

    response = await client.get(
        "/api/v1/users/me",
        headers={"Authorization": f"Bearer {_mint(user_id=user.id, guild_id=1)}"},
    )

    assert response.status_code == 401


@pytest.mark.integration
async def test_keys_without_the_grant_verify_nothing(
    client: AsyncClient, session: AsyncSession
):
    """The key set says who signs; the grant says whether that app may act."""
    user = await create_user(session, email="ungranted@example.com")
    await _register(session, grants=[])

    response = await client.get(
        "/api/v1/users/me",
        headers={"Authorization": f"Bearer {_mint(user_id=user.id, guild_id=1)}"},
    )

    assert response.status_code == 401


@pytest.mark.integration
async def test_a_kid_no_registration_published_verifies_nothing(
    client: AsyncClient, session: AsyncSession
):
    user = await create_user(session, email="unknown-kid@example.com")
    await _register(session, grants=["delegation"])

    response = await client.get(
        "/api/v1/users/me",
        headers={
            "Authorization": f"Bearer {_mint(user_id=user.id, guild_id=1, kid='rotated-away')}"
        },
    )

    assert response.status_code == 401


@pytest.mark.integration
async def test_delegate_available_follows_the_registration(session: AsyncSession):
    assert await delegate_available() is False

    await _register(session, grants=["delegation"])
    assert await delegate_available() is True
