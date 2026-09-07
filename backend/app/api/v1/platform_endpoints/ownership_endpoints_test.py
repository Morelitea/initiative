"""The guild-admin ownership screens, over HTTP.

Handing content to somebody is the one place ownership moves by hand, so the
request runs inside the guild's own schema, as that guild's admin. Everything
it reads has to be readable from there — a guild session reads people through
``guild_member_profiles``, not ``users`` — and the service-level tests for
``app.services.tenant.ownership`` run on the setup session, which sees more
than a request does.
"""

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.tools import Tool
from app.models.platform.guild import GuildRole
from app.services.tenant import ownership as ownership_service
from app.testing import (
    TOOL_FACTORIES,
    route_session_to_guild,
)

pytestmark = pytest.mark.integration


async def _released_project(session: AsyncSession, actor):
    """A project in ``actor``'s initiative that nobody owns."""
    project = await TOOL_FACTORIES[Tool.project](session, actor.initiative, actor.user)
    await route_session_to_guild(session, actor.guild.id)
    await ownership_service.set_resource_owner(
        session, tool=Tool.project, row=project, new_owner_id=None
    )
    await session.commit()
    return project


async def test_a_guild_admin_can_claim_unowned_content(
    client: AsyncClient, session: AsyncSession, acting_user
):
    admin = await acting_user(guild_role=GuildRole.admin, initiative=True)
    project = await _released_project(session, admin)

    response = await client.post(
        f"/api/v1/g/{admin.guild.id}/users/unowned-content/claim",
        headers=admin.headers,
        json={"new_owner_id": admin.user.id},
    )
    assert response.status_code == 200, response.text
    assert response.json()["total"] >= 1, response.text

    await route_session_to_guild(session, admin.guild.id)
    owners = await ownership_service.summarize_unowned_content(
        session, guild_id=admin.guild.id
    )
    assert (Tool.project, project.id) not in {(i.tool, i.id) for i in owners}


async def test_content_cannot_be_handed_to_an_ordinary_member(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The recipient check is the same query, from the other side."""
    admin = await acting_user(guild_role=GuildRole.admin, initiative=True)
    member = await acting_user(
        guild_role=GuildRole.member,
        guild=admin.guild,
        initiative=admin.initiative,
        initiative_role="member",
    )
    await _released_project(session, admin)

    response = await client.post(
        f"/api/v1/g/{admin.guild.id}/users/unowned-content/claim",
        headers=admin.headers,
        json={"new_owner_id": member.user.id},
    )
    assert response.status_code == 400, response.text
    assert response.json()["detail"] == "OWNER_MUST_BE_GUILD_ADMIN"


async def test_ownership_transfers_between_guild_admins(
    client: AsyncClient, session: AsyncSession, acting_user
):
    owner = await acting_user(guild_role=GuildRole.admin, initiative=True)
    receiver = await acting_user(
        guild_role=GuildRole.admin,
        guild=owner.guild,
        initiative=owner.initiative,
        initiative_role="project_manager",
    )
    await TOOL_FACTORIES[Tool.project](session, owner.initiative, owner.user)

    response = await client.post(
        f"/api/v1/g/{owner.guild.id}/users/{owner.user.id}/transfer-ownership",
        headers=owner.headers,
        json={"new_owner_id": receiver.user.id},
    )
    assert response.status_code == 200, response.text
    assert response.json()["total"] >= 1, response.text
