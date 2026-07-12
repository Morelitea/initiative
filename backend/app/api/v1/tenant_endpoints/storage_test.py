"""The SPA storage-usage read backing the guild usage panel.

Invariants: it returns the guild-scoped SUM(uploads.size_bytes); it is
guild-ADMIN only (the guild-wide total backs the admin settings surface and,
like ``status``, is not disclosed to regular members); and a non-member
can't reach another guild's usage at all (RLS).
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.guild import GuildRole
from app.testing import create_upload

pytestmark = [pytest.mark.integration, pytest.mark.database]


async def test_storage_usage_sums_guild_bytes(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(guild_role=GuildRole.admin)
    await create_upload(session, a.guild, a.user, size_bytes=2048)
    await create_upload(session, a.guild, a.user, size_bytes=52)

    response = await client.get(a.g("/storage/usage"), headers=a.headers)
    assert response.status_code == 200, response.text
    assert response.json() == {"guild_id": a.guild.id, "usage_bytes": 2100}


async def test_storage_usage_zero_for_empty_guild(client: AsyncClient, acting_user):
    a = await acting_user(guild_role=GuildRole.admin)
    response = await client.get(a.g("/storage/usage"), headers=a.headers)
    assert response.status_code == 200, response.text
    assert response.json() == {"guild_id": a.guild.id, "usage_bytes": 0}


async def test_storage_usage_requires_guild_admin(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """A regular member of the SAME guild is refused — the guild-wide total
    is an admin-settings figure, not member-visible data."""
    admin = await acting_user(guild_role=GuildRole.admin)
    await create_upload(session, admin.guild, admin.user, size_bytes=999)

    member = await acting_user(guild_role=GuildRole.member, guild=admin.guild)
    response = await client.get(member.g("/storage/usage"), headers=member.headers)
    assert response.status_code == 403
    assert response.json()["detail"] == "GUILD_ADMIN_REQUIRED"


async def test_storage_usage_requires_membership(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """A user who isn't in the guild can't read its usage — RLS hides the
    guild (404), never leaks another guild's stored-byte total."""
    owner = await acting_user(guild_role=GuildRole.admin)
    await create_upload(session, owner.guild, owner.user, size_bytes=999)

    outsider = await acting_user(guild_role=GuildRole.member)  # a different guild
    response = await client.get(
        f"/api/v1/g/{owner.guild.id}/storage/usage", headers=outsider.headers
    )
    assert response.status_code in (403, 404)
