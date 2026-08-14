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
from app.testing import create_guild, create_guild_membership, create_user
from app.testing.delegation import (
    DELEGATE_KID,
    install_delegate,
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


async def _acting_in_a_guild_that_installed_it(session: AsyncSession, email: str):
    """A user, their guild, and that guild's install of the delegate.

    Every case below varies one thing about the *registration*, so the install
    side is held constant here rather than restated each time.
    """
    user = await create_user(session, email=email)
    guild = await create_guild(session, creator=user)
    await create_guild_membership(session, user=user, guild=guild)
    await install_delegate(session, guild, creator=user)
    return user, guild


async def _call_as_delegate(client: AsyncClient, user_id: int, guild_id: int) -> int:
    response = await client.get(
        "/api/v1/users/me",
        headers={
            "Authorization": (
                f"Bearer {mint_delegation_token(user_id=user_id, guild_id=guild_id)}"
            )
        },
    )
    return response.status_code


@pytest.mark.integration
async def test_a_granted_registration_verifies_the_token(
    client: AsyncClient, session: AsyncSession
):
    user, guild = await _acting_in_a_guild_that_installed_it(
        session, "delegated@example.com"
    )
    await register_delegate(session)

    assert await _call_as_delegate(client, user.id, guild.id) == 200


@pytest.mark.integration
async def test_the_kill_switch_ends_delegation(
    client: AsyncClient, session: AsyncSession
):
    user, guild = await _acting_in_a_guild_that_installed_it(
        session, "switched-off@example.com"
    )
    await register_delegate(session, enabled=False)

    assert await _call_as_delegate(client, user.id, guild.id) == 401


@pytest.mark.integration
async def test_keys_without_the_grant_verify_nothing(
    client: AsyncClient, session: AsyncSession
):
    """The key set says who signs; the grant says whether that app may act."""
    user, guild = await _acting_in_a_guild_that_installed_it(
        session, "ungranted@example.com"
    )
    await register_delegate(session, grants=())

    assert await _call_as_delegate(client, user.id, guild.id) == 401


@pytest.mark.integration
async def test_a_kid_no_registration_published_verifies_nothing(
    client: AsyncClient, session: AsyncSession
):
    user, guild = await _acting_in_a_guild_that_installed_it(
        session, "unknown-kid@example.com"
    )
    await register_delegate(session, key_set=delegation_jwks("some-other-generation"))

    assert await _call_as_delegate(client, user.id, guild.id) == 401


@pytest.mark.integration
async def test_a_shared_kid_does_not_shadow_the_app_that_signed(
    client: AsyncClient, session: AsyncSession
):
    """A ``kid`` is an opaque label its owner picks, so two apps may choose the
    same one. Every match is tried, and the call belongs to whichever key
    actually signed it — including for the install it is then held to, which
    the namesake here does not have."""
    user, guild = await _acting_in_a_guild_that_installed_it(
        session, "shared-kid@example.com"
    )
    # A namesake sorting first, publishing a different key under the same kid.
    await register_delegate(
        session,
        public_id="aaa.namesake",
        key_set=foreign_jwks(DELEGATE_KID),
    )
    await register_delegate(session)

    assert await _call_as_delegate(client, user.id, guild.id) == 200


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


@pytest.mark.integration
async def test_an_app_acts_only_where_it_was_installed(
    client: AsyncClient, session: AsyncSession
):
    """The registration says the app may delegate; the install says this guild
    chose it. Both are required, so uninstalling ends the app's reach — and it
    ends it the way every other delegation refusal does, by not authenticating
    the call at all."""
    user = await create_user(session, email="uninstalled@example.com")
    guild = await create_guild(session, creator=user)
    await create_guild_membership(session, user=user, guild=guild)
    await register_delegate(session)

    refused = await client.get(
        f"/api/v1/g/{guild.id}/initiatives/",
        headers={
            "Authorization": (
                f"Bearer {mint_delegation_token(user_id=user.id, guild_id=guild.id)}"
            )
        },
    )
    assert refused.status_code == 401

    await install_delegate(session, guild)

    allowed = await client.get(
        f"/api/v1/g/{guild.id}/initiatives/",
        headers={
            "Authorization": (
                f"Bearer {mint_delegation_token(user_id=user.id, guild_id=guild.id)}"
            )
        },
    )
    assert allowed.status_code == 200, allowed.text


@pytest.mark.integration
async def test_a_switched_off_install_stops_the_app(
    client: AsyncClient, session: AsyncSession
):
    """An install turned off is not one the app may act through, the same as
    one that was never made."""
    user = await create_user(session, email="install-off@example.com")
    guild = await create_guild(session, creator=user)
    await create_guild_membership(session, user=user, guild=guild)
    await register_delegate(session)
    install = await install_delegate(session, guild)
    install.enabled = False
    session.add(install)
    await session.commit()

    response = await client.get(
        f"/api/v1/g/{guild.id}/initiatives/",
        headers={
            "Authorization": (
                f"Bearer {mint_delegation_token(user_id=user.id, guild_id=guild.id)}"
            )
        },
    )
    assert response.status_code == 401
