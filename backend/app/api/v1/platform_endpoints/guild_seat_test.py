"""The guild's top seat: who gets it, and who Postgres lets write as it."""

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db.session import set_rls_context
from app.models.platform.guild import GuildRole
from app.services import rls as rls_service
from app.testing.factories import (
    create_guild,
    create_guild_membership,
    create_user,
    get_auth_headers,
)

pytestmark = [pytest.mark.integration, pytest.mark.auth]


async def test_whoever_makes_a_community_holds_its_seat(
    client: AsyncClient, session: AsyncSession
):
    """Starting a community means holding all of it, billing and sign-in
    included — and there is somebody to pass the seat to only because the
    first person has it."""
    founder = await create_user(session)

    created = await client.post(
        "/api/v1/guilds/",
        headers=get_auth_headers(founder),
        json={"name": "Founders"},
    )
    assert created.status_code == 201, created.text
    assert created.json()["role"] == "superadmin"


async def test_the_seat_is_read_from_postgres_not_from_the_enum(
    session: AsyncSession,
):
    """The app asks ``public.guild_superadmin`` rather than comparing a Python
    value, so the endpoint and the policies cannot drift apart."""
    guild = await create_guild(session)
    seat = await create_user(session)
    admin = await create_user(session)
    await create_guild_membership(
        session, user=seat, guild=guild, role=GuildRole.superadmin
    )
    await create_guild_membership(
        session, user=admin, guild=guild, role=GuildRole.admin
    )
    await session.commit()

    for user, expected in ((seat, True), (admin, False)):
        await set_rls_context(session, user_id=int(user.id))
        held = await rls_service.holds_guild_seat(
            session, guild_id=int(guild.id), user_id=int(user.id)
        )
        assert held is expected


async def test_postgres_refuses_the_write_to_anyone_but_the_seat(
    session: AsyncSession, role_session
):
    """The rule stands on its own, with no endpoint in front of it.

    Both members are routed into the guild exactly as a request would be, and
    the same INSERT is attempted as each. What separates them is the policy.
    """
    guild = await create_guild(session)
    seat = await create_user(session)
    admin = await create_user(session)
    await create_guild_membership(
        session, user=seat, guild=guild, role=GuildRole.superadmin
    )
    await create_guild_membership(
        session, user=admin, guild=guild, role=GuildRole.admin
    )
    await session.commit()

    insert = text(
        "INSERT INTO public.guild_auth_policies (guild_id, policy, updated_at) "
        "VALUES (:g, 'open', now())"
    )
    # The request path's own login role, not the superuser the setup above
    # runs as — this is the boundary under test.
    writer = await role_session("app_user")

    await set_rls_context(
        writer,
        user_id=int(admin.id),
        guild_id=int(guild.id),
        guild_role="admin",
    )
    with pytest.raises(DBAPIError):
        await writer.exec(insert.bindparams(g=int(guild.id)))
    await writer.rollback()

    await set_rls_context(
        writer,
        user_id=int(seat.id),
        guild_id=int(guild.id),
        guild_role="admin",
    )
    await writer.exec(insert.bindparams(g=int(guild.id)))
    await writer.rollback()


async def test_billing_is_the_seats_too(
    client: AsyncClient, session: AsyncSession, monkeypatch
):
    """What a community pays for goes with its sign-in, not with running it."""
    # A deployment with no portal answers 404 before it asks who is calling,
    # so there has to be one for the question to be reached at all.
    from app.core.config import settings

    monkeypatch.setattr(settings, "BILLING_URL", "https://billing.example")
    guild = await create_guild(session)
    seat = await create_user(session)
    admin = await create_user(session)
    await create_guild_membership(
        session, user=seat, guild=guild, role=GuildRole.superadmin
    )
    await create_guild_membership(
        session, user=admin, guild=guild, role=GuildRole.admin
    )
    await session.commit()

    refused = await client.post(
        f"/api/v1/guilds/{guild.id}/billing/handoff", headers=get_auth_headers(admin)
    )
    assert refused.status_code == 403
    assert refused.json()["detail"] == "GUILD_SUPERADMIN_REQUIRED"

    # The seat gets past the gate; whether a portal is configured is the
    # deployment's business and the next thing the endpoint checks.
    allowed = await client.post(
        f"/api/v1/guilds/{guild.id}/billing/handoff", headers=get_auth_headers(seat)
    )
    assert allowed.status_code != 403, allowed.text
