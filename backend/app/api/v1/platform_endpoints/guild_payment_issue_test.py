import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.models.platform.guild import GuildRole, GuildStatus
from app.services.platform import billing_ping
from app.testing.factories import (
    create_guild,
    create_guild_membership,
    create_user,
    get_auth_headers,
)

pytestmark = [pytest.mark.integration]


@pytest.fixture
def asked(monkeypatch):
    calls: list[int] = []

    async def _payment_failed(guild_id: int) -> bool:
        calls.append(guild_id)
        return True

    monkeypatch.setattr(billing_ping, "guild_payment_failed", _payment_failed)
    monkeypatch.setattr(settings, "BILLING_URL", "https://billing.example")
    return calls


async def _guild_with_seat(session: AsyncSession, status: GuildStatus):
    guild = await create_guild(session)
    seat = await create_user(session)
    admin = await create_user(session)
    await create_guild_membership(
        session, user=seat, guild=guild, role=GuildRole.superadmin
    )
    await create_guild_membership(
        session, user=admin, guild=guild, role=GuildRole.admin
    )
    guild.status = status.value
    session.add(guild)
    await session.commit()
    return guild, seat, admin


def _url(guild_id: int) -> str:
    return f"/api/v1/guilds/{guild_id}/billing/payment-issue"


async def test_only_the_seat_may_ask(client: AsyncClient, session: AsyncSession, asked):
    guild, _, admin = await _guild_with_seat(session, GuildStatus.read_only)
    response = await client.get(_url(guild.id), headers=get_auth_headers(admin))
    assert response.status_code == 403
    assert asked == []


@pytest.mark.parametrize("status", [GuildStatus.read_only, GuildStatus.suspended])
async def test_the_seat_of_a_restricted_guild_gets_the_answer(
    client: AsyncClient, session: AsyncSession, asked, status
):
    guild, seat, _ = await _guild_with_seat(session, status)
    response = await client.get(_url(guild.id), headers=get_auth_headers(seat))
    assert response.status_code == 200, response.text
    assert response.json() == {"payment_failed": True}
    assert asked == [guild.id]


async def test_an_active_guild_is_never_asked_about(
    client: AsyncClient, session: AsyncSession, asked
):
    guild, seat, _ = await _guild_with_seat(session, GuildStatus.active)
    response = await client.get(_url(guild.id), headers=get_auth_headers(seat))
    assert response.json() == {"payment_failed": False}
    assert asked == []


async def test_no_portal_is_never_asked_about(
    client: AsyncClient, session: AsyncSession, asked, monkeypatch
):
    monkeypatch.setattr(settings, "BILLING_URL", "")
    guild, seat, _ = await _guild_with_seat(session, GuildStatus.read_only)
    response = await client.get(_url(guild.id), headers=get_auth_headers(seat))
    assert response.json() == {"payment_failed": False}
    assert asked == []
