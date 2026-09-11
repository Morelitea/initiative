"""The exchange that lets one app name a guild and a member to another.

Each app holds references minted at its own install, so a delegate's names mean
nothing to the app it is calling. Only this deployment holds both, and these
assert that what comes back is in the **target's** terms and carries the
delegate in ``act`` — plus the three states a delegate can act on, told apart.

See ``history/opaque-identity-design.md`` §12.
"""

from __future__ import annotations

import jwt
import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core import config as config_module
from app.core.messages import DelegationExchangeMessages
from app.services.marketplace.app_refs import ensure_app_guild_ref, ensure_app_ref
from app.services.marketplace.context_jwt_test import _PRIVATE_PEM
from app.services.marketplace.registration_lookup import invalidate_registrations
from app.testing import create_guild, create_guild_app, create_user
from app.testing.app_channel import register_app_service
from app.testing.delegation import (
    DELEGATE_PUBLIC_ID,
    authorize_delegate,
    delegate_guild_ref,
    delegate_subject,
    install_delegate,
    mint_delegation_token,
    register_delegate,
)

EXCHANGE = "/api/v1/app-platform/delegation/exchange"
TARGET_PUBLIC_ID = "tests.shop"
TARGET_LISTING = "TESTAPP0000001"

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
async def _platform_signing(session: AsyncSession):
    """A real key, because these read what was actually signed."""
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(
            config_module.settings,
            "APP_PLATFORM_SIGNING_PRIVATE_KEY_PEM",
            _PRIVATE_PEM,
        )
        await register_delegate(session)
        yield
    invalidate_registrations()


async def _delegated(session: AsyncSession, *, install_target: bool = True):
    """A guild where the delegate may act for a member, with a second app in it."""
    owner = await create_user(session, email="owner@example.com")
    guild = await create_guild(session, creator=owner)
    await install_delegate(session, guild, creator=owner)

    member = await create_user(session, email="member@example.com")
    await authorize_delegate(session, guild, member)
    subject = await delegate_subject(session, guild, member)

    await register_app_service(
        session, public_id=TARGET_PUBLIC_ID, listing_uid=TARGET_LISTING
    )
    target = None
    if install_target:
        target = await create_guild_app(
            session,
            guild,
            owner,
            definition={
                "app_kind": "service",
                "service": {"public_id": TARGET_PUBLIC_ID},
            },
            listing_uid=TARGET_LISTING,
            name="Shop",
        )
    return guild, member, subject, target


async def _post(client: AsyncClient, session, guild, subject, audience: str):
    token = mint_delegation_token(
        subject=subject, guild_ref=await delegate_guild_ref(session, guild)
    )
    return await client.post(
        EXCHANGE,
        json={"audience": audience},
        headers={"Authorization": f"Bearer {token}"},
    )


async def test_the_token_names_the_pair_in_the_targets_terms(
    client: AsyncClient, session: AsyncSession
):
    """The whole point: what comes back is addressed to the target and names
    the same guild and member by the references minted at *its* install."""
    guild, member, subject, target = await _delegated(session)

    response = await _post(client, session, guild, subject, TARGET_PUBLIC_ID)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["expires_in_seconds"] > 0

    claims = jwt.decode(body["token"], options={"verify_signature": False})
    assert claims["aud"] == f"initiative-app:{TARGET_PUBLIC_ID}"
    assert claims["sub"] == await ensure_app_ref(
        guild_id=guild.id, app_install_id=target.id, user_id=member.id
    )
    assert claims["guild_ref"] == await ensure_app_guild_ref(
        guild_id=guild.id, app_install_id=target.id
    )
    # Who asked, as RFC 8693 records it.
    assert claims["act"] == {"public_id": DELEGATE_PUBLIC_ID}
    assert claims["jti"]


async def test_nothing_the_delegate_holds_travels_on(
    client: AsyncClient, session: AsyncSession
):
    """The delegate's own references are unrelated values, and stay that way."""
    guild, _member, subject, _target = await _delegated(session)
    delegates_guild_ref = await delegate_guild_ref(session, guild)

    response = await _post(client, session, guild, subject, TARGET_PUBLIC_ID)
    claims = jwt.decode(response.json()["token"], options={"verify_signature": False})

    assert claims["guild_ref"] != delegates_guild_ref
    assert claims["sub"] != subject
    # And no row id of ours is in there at all.
    assert "guild_id" not in claims and "app_install_id" not in claims


async def test_an_audience_this_deployment_does_not_run_is_refused(
    client: AsyncClient, session: AsyncSession
):
    guild, _member, subject, _target = await _delegated(session)
    response = await _post(client, session, guild, subject, "nobody.at.all")
    assert response.status_code == 404
    assert response.json()["detail"] == DelegationExchangeMessages.UNKNOWN_AUDIENCE


async def test_a_guild_without_that_app_is_refused(
    client: AsyncClient, session: AsyncSession
):
    """A delegate may act in this guild and still have nowhere to act."""
    guild, _member, subject, _target = await _delegated(session, install_target=False)
    response = await _post(client, session, guild, subject, TARGET_PUBLIC_ID)
    assert response.status_code == 404
    assert response.json()["detail"] == DelegationExchangeMessages.NOT_INSTALLED


async def test_a_caller_holding_no_delegation_has_nothing_to_re_address(
    client: AsyncClient, acting_user
):
    """The operation is 'address what you already hold', so a session is not a
    smaller version of it — it is a different thing entirely."""
    a = await acting_user()
    response = await client.post(
        EXCHANGE, json={"audience": TARGET_PUBLIC_ID}, headers=a.headers
    )
    assert response.status_code == 403
    assert response.json()["detail"] == DelegationExchangeMessages.NOT_DELEGATED
