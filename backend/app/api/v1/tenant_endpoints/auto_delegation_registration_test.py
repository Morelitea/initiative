"""What a registration says about whether its app may act as a member.

The companion to ``auto_delegation_test.py``, which exercises the auth dep's
own checks with a delegate already in place. Here the subject is the
registration itself: the grant, the kill switch, and which key a ``kid``
resolves to.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core import config as config_module
from app.services.marketplace.registration_lookup import (
    any_delegate_registered,
    delegation_keys_for,
    invalidate_registrations,
)
from app.testing import create_user
from app.testing.delegation import (
    DELEGATE_KID,
    delegation_jwks,
    foreign_jwks,
    mint_delegation_token,
    register_delegate,
)


@pytest.fixture(autouse=True)
def _app_platform_configured(monkeypatch):
    """Registrations are reachable on this deployment, which is the cheap gate
    the auth dep reads before it resolves anything."""
    monkeypatch.setattr(
        config_module.settings,
        "APP_PLATFORM_SIGNING_PRIVATE_KEY_PEM",
        "-----BEGIN PRIVATE KEY-----",
    )
    invalidate_registrations()
    yield
    invalidate_registrations()


async def _call_as_delegate(client: AsyncClient, user_id: int) -> int:
    response = await client.get(
        "/api/v1/users/me",
        headers={
            "Authorization": f"Bearer {mint_delegation_token(user_id=user_id, guild_id=1)}"
        },
    )
    return response.status_code


@pytest.mark.integration
async def test_a_granted_registration_verifies_the_token(
    client: AsyncClient, session: AsyncSession
):
    user = await create_user(session, email="delegated@example.com")
    await register_delegate(session)

    assert await _call_as_delegate(client, user.id) == 200


@pytest.mark.integration
async def test_the_kill_switch_ends_delegation(
    client: AsyncClient, session: AsyncSession
):
    user = await create_user(session, email="switched-off@example.com")
    await register_delegate(session, enabled=False)

    assert await _call_as_delegate(client, user.id) == 401


@pytest.mark.integration
async def test_keys_without_the_grant_verify_nothing(
    client: AsyncClient, session: AsyncSession
):
    """The key set says who signs; the grant says whether that app may act."""
    user = await create_user(session, email="ungranted@example.com")
    await register_delegate(session, grants=())

    assert await _call_as_delegate(client, user.id) == 401


@pytest.mark.integration
async def test_a_kid_no_registration_published_verifies_nothing(
    client: AsyncClient, session: AsyncSession
):
    user = await create_user(session, email="unknown-kid@example.com")
    await register_delegate(session, key_set=delegation_jwks("some-other-generation"))

    assert await _call_as_delegate(client, user.id) == 401


@pytest.mark.integration
async def test_a_shared_kid_does_not_shadow_the_app_that_signed(
    client: AsyncClient, session: AsyncSession
):
    """A ``kid`` is an opaque label its owner picks, so two apps may choose the
    same one. Every match is offered to the verifier, and the token belongs to
    whichever key actually signed it."""
    user = await create_user(session, email="shared-kid@example.com")
    # A namesake registered first, publishing a different key under the same
    # kid — the token is not its.
    await register_delegate(
        session,
        public_id="aaa.namesake",
        key_set=foreign_jwks(DELEGATE_KID),
    )
    await register_delegate(session)

    assert await _call_as_delegate(client, user.id) == 200


@pytest.mark.integration
async def test_resolution_offers_every_registration_publishing_the_kid(
    session: AsyncSession,
):
    await register_delegate(session, public_id="aaa.namesake")
    await register_delegate(session)

    assert len(await delegation_keys_for(DELEGATE_KID)) == 2
    assert await delegation_keys_for("nobody-published-this") == ()


@pytest.mark.integration
async def test_any_delegate_registered_follows_the_registration(
    session: AsyncSession,
):
    assert await any_delegate_registered() is False

    await register_delegate(session)
    assert await any_delegate_registered() is True
