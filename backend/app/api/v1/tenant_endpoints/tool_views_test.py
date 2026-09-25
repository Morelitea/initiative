"""The recent-view pair, proved once for every tool.

``POST``/``DELETE`` ``/{tool}/{id}/view`` are mounted from the resource-access
registry (``tenant_endpoints/tool_views.py``), so what is worth asserting is
that the pair behaves the same whichever tool is named — the entities come from
``TOOL_FACTORIES`` and the cases are parametrised over the ``Tool`` enum, which
means a new tool is exercised here the moment it exists.

The cross-guild tabs-bar list itself is ``recents_test.py``; what these assert
of it is only that recording and forgetting reach it.
"""

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.tools import Tool
from app.models.platform.guild import GuildRole
from app.testing import create_tool_entity, enable_all_tools

RECENTS = "/api/v1/recents/"

#: Every tool, as its own test case.
TOOLS = pytest.mark.parametrize("tool", list(Tool), ids=[t.value for t in Tool])


async def _entity(session: AsyncSession, actor, tool: Tool):
    """One instance of ``tool``, owned by ``actor``, in an all-tools initiative."""
    await enable_all_tools(session, actor.initiative)
    return await create_tool_entity(session, tool, actor.initiative, actor.user)


@pytest.mark.integration
@TOOLS
async def test_recording_a_view_puts_the_tool_in_the_tabs_bar(
    client: AsyncClient, session: AsyncSession, acting_user, tool: Tool
):
    a = await acting_user(guild_role=GuildRole.member, initiative=True)
    entity = await _entity(session, a, tool)

    response = await client.post(
        a.g(f"/{tool.route_segment}/{entity.id}/view"), headers=a.headers
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["entity_type"] == tool.value
    assert body["entity_id"] == entity.id
    assert body["last_viewed_at"]

    listed = await client.get(RECENTS, headers=a.headers)
    assert listed.status_code == 200, listed.text
    assert [(i["entity_type"], i["entity_id"]) for i in listed.json()] == [
        (tool.value, entity.id)
    ]


@pytest.mark.integration
@TOOLS
async def test_clearing_a_view_forgets_it(
    client: AsyncClient, session: AsyncSession, acting_user, tool: Tool
):
    a = await acting_user(guild_role=GuildRole.member, initiative=True)
    entity = await _entity(session, a, tool)
    path = a.g(f"/{tool.route_segment}/{entity.id}/view")

    assert (await client.post(path, headers=a.headers)).status_code == 200

    response = await client.delete(path, headers=a.headers)
    assert response.status_code == 204, response.text

    listed = await client.get(RECENTS, headers=a.headers)
    assert listed.status_code == 200
    assert listed.json() == []

    # Forgetting what was already forgotten is the same answer.
    assert (await client.delete(path, headers=a.headers)).status_code == 204


@pytest.mark.integration
@TOOLS
async def test_someone_outside_the_initiative_gets_the_tools_not_found(
    client: AsyncClient, session: AsyncSession, acting_user, tool: Tool
):
    """A guild member who is not in the initiative reaches none of its content,
    and both halves of the pair say so in the tool's own words."""
    a = await acting_user(guild_role=GuildRole.member, initiative=True)
    entity = await _entity(session, a, tool)
    outsider = await acting_user(guild_role=GuildRole.member, guild=a.guild)
    path = outsider.g(f"/{tool.route_segment}/{entity.id}/view")

    recorded = await client.post(path, headers=outsider.headers)
    assert recorded.status_code == 404, recorded.text
    assert recorded.json()["detail"] == tool.not_found_code

    cleared = await client.delete(path, headers=outsider.headers)
    assert cleared.status_code == 404, cleared.text
    assert cleared.json()["detail"] == tool.not_found_code

    listed = await client.get(RECENTS, headers=outsider.headers)
    assert listed.status_code == 200
    assert listed.json() == []
