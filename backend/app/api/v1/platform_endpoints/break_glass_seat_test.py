"""An operator appoints a community's superadmin through the community's own
role route, holding the break-glass pair.

The case this covers: the only superadmin cannot pass the seat on themselves
(unreachable, asking for erasure, banned). Breaking glass issues a
``read_write`` content grant and a ``superadmin`` settings grant; the second is
what lets the holder seat somebody from inside the community, and doing so
clears the account's deletion blocker.
"""

import pytest
from httpx import AsyncClient
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.guild import GuildMembership, GuildRole

pytestmark = pytest.mark.integration

BREAK_GLASS = "/api/v1/access-grants/break-glass"


async def test_a_break_glass_holder_seats_a_superadmin_from_the_guilds_own_route(
    client: AsyncClient, session: AsyncSession, acting_user
):
    keyholder = await acting_user(guild_role=GuildRole.superadmin)
    guild_id = keyholder.guild.id
    keyholder_id = keyholder.user.id
    successor = await acting_user(guild_role=GuildRole.member, guild=keyholder.guild)
    successor_id = successor.user.id
    operator = await acting_user("operator")

    role_route = f"/api/v1/guilds/{guild_id}/members/{successor_id}"
    eligibility = f"/api/v1/admin/users/{keyholder_id}/deletion-eligibility"

    blocked = await client.get(eligibility, headers=operator.headers)
    assert blocked.status_code == 200, blocked.text
    assert blocked.json()["can_delete"] is False
    assert [g["guild_id"] for g in blocked.json()["guild_blockers"]] == [guild_id]

    # Not a member and no grant yet: the route is not theirs.
    before = await client.patch(
        role_route, headers=operator.headers, json={"role": "superadmin"}
    )
    assert before.status_code == 403, before.text

    issued = await client.post(
        BREAK_GLASS,
        json={"guild_id": guild_id, "reason": "sole superadmin unreachable"},
        headers=operator.headers,
    )
    assert issued.status_code == 201, issued.text

    seated = await client.patch(
        role_route, headers=operator.headers, json={"role": "superadmin"}
    )
    assert seated.status_code == 204, seated.text

    session.expire_all()
    row = (
        await session.exec(
            select(GuildMembership).where(
                GuildMembership.guild_id == guild_id,
                GuildMembership.user_id == successor_id,
            )
        )
    ).one()
    assert row.role == GuildRole.superadmin

    cleared = await client.get(eligibility, headers=operator.headers)
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["can_delete"] is True
    assert cleared.json()["guild_blockers"] == []
