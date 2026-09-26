"""Deleting a tool, proved once for every tool.

``DELETE /{tool}/{id}`` is mounted from the resource-access registry
(``tenant_endpoints/tool_lifecycle.py``), so the cases are parametrised over the
``Tool`` enum and a new tool is exercised here the moment it exists. What goes
into the trash with it is ``soft_delete_test``'s; restoring it is ``trash_test``'s.

The queue and counter-group signal tests this replaces asserted the same thing
for two tools under their own event names.
"""

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.tools import Tool
from app.models.platform.guild import GuildRole
from app.models.tenant.resource_grant import ResourceAccessLevel
from app.testing import create_resource_grant, create_tool_entity, enable_all_tools

#: Every tool, as its own test case.
TOOLS = pytest.mark.parametrize("tool", list(Tool), ids=[t.value for t in Tool])


async def _entity(session: AsyncSession, actor, tool: Tool):
    """One instance of ``tool``, owned by ``actor``, in an all-tools initiative."""
    await enable_all_tools(session, actor.initiative)
    return await create_tool_entity(session, tool, actor.initiative, actor.user)


@TOOLS
async def test_the_owner_deletes_it_and_the_room_is_told(
    client: AsyncClient, session: AsyncSession, acting_user, tool: Tool, monkeypatch
):
    from app.services.content_sockets import sockets

    a = await acting_user(guild_role=GuildRole.member, initiative=True)
    entity = await _entity(session, a, tool)
    signalled: list[tuple] = []
    monkeypatch.setattr(sockets, "signal", lambda *args: signalled.append(args))

    response = await client.delete(
        a.g(f"/{tool.route_segment}/{entity.id}"), headers=a.headers
    )

    assert response.status_code == 204, response.text
    assert signalled == [(a.guild.id, tool, entity.id, "deleted")]
    gone = await client.get(
        a.g(f"/{tool.route_segment}/{entity.id}"), headers=a.headers
    )
    assert gone.status_code == 404


@TOOLS
async def test_writing_to_it_is_not_enough_to_delete_it(
    client: AsyncClient, session: AsyncSession, acting_user, tool: Tool
):
    a = await acting_user(guild_role=GuildRole.member, initiative=True)
    entity = await _entity(session, a, tool)
    b = await acting_user(
        guild_role=GuildRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )
    await create_resource_grant(
        session, entity, level=ResourceAccessLevel.write, user=b.user
    )

    response = await client.delete(
        b.g(f"/{tool.route_segment}/{entity.id}"), headers=b.headers
    )

    assert response.status_code == 403, response.text
    still = await client.get(
        a.g(f"/{tool.route_segment}/{entity.id}"), headers=a.headers
    )
    assert still.status_code == 200
