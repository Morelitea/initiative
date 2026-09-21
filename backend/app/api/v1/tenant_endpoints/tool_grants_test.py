"""Sharing a tool, proved once for every tool.

``PUT /{tool}/{id}/grants`` is mounted from the resource-access registry
(``tenant_endpoints/tool_grants.py``), so what is worth asserting is that it
behaves the same whichever tool is named — the entities come from
``TOOL_FACTORIES`` and the cases are parametrised over the ``Tool`` enum, which
means a new tool is exercised here the moment it exists.

What survives here from the per-tool copies these replace:

- *the owner shares it* — ``queues_test.test_set_queue_grants`` and
  ``dashboards_test.test_set_grants_replaces_sharing`` (the grantee can then
  write, and the owner's own grant is kept);
- *a role can be named instead of a person* —
  ``queues_test.test_set_queue_role_grants``;
- *a reader cannot re-share* — the first half of
  ``calendars_test.test_set_calendar_grants_owner_only``. Its second half —
  that revoking every non-owner grant hides the row again — is already proved
  per tool where the visibility rules live (``calendars_test`` and
  ``dashboards_test`` both strip grants and read back).

What stays where it is: sharing that runs into the initiative-role gate
(``queues_test.test_sharing_does_not_reach_past_the_role_gate``), the projects'
own side effect of a grant change (``projects_test``'s demoted-assignee
tests), and every test that merely *uses* the route to set up something else.
"""

import pytest
from httpx import AsyncClient
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.tools import Tool
from app.models.platform.guild import GuildRole
from app.models.tenant.initiative import InitiativeRoleModel
from app.testing import create_tool_entity, enable_all_tools

#: Every tool, as its own test case.
TOOLS = pytest.mark.parametrize("tool", list(Tool), ids=[t.value for t in Tool])


def _segment(tool: Tool) -> str:
    """The URL segment the tool is addressed by — its plural in kebab case."""
    return tool.plural.replace("_", "-")


async def _entity(session: AsyncSession, actor, tool: Tool):
    """One instance of ``tool``, owned by ``actor``, in an all-tools initiative."""
    await enable_all_tools(session, actor.initiative)
    return await create_tool_entity(session, tool, actor.initiative, actor.user)


@pytest.mark.integration
@TOOLS
async def test_the_owner_shares_it_with_somebody(
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

    response = await client.put(
        a.g(f"/{_segment(tool)}/{entity.id}/grants"),
        headers=a.headers,
        json=[{"user_id": b.user.id, "level": "write"}],
    )
    assert response.status_code == 200, response.text
    grants = response.json()["grants"]
    assert [grant["level"] for grant in grants if grant["user_id"] == b.user.id] == [
        "write"
    ]
    # The owner is kept whether or not the replacement list names them.
    assert [grant["level"] for grant in grants if grant["user_id"] == a.user.id] == [
        "owner"
    ]


@pytest.mark.integration
@TOOLS
async def test_a_role_can_be_named_instead_of_a_person(
    client: AsyncClient, session: AsyncSession, acting_user, tool: Tool
):
    a = await acting_user(guild_role=GuildRole.member, initiative=True)
    entity = await _entity(session, a, tool)
    member_role = (
        await session.exec(
            select(InitiativeRoleModel).where(
                InitiativeRoleModel.initiative_id == a.initiative.id,
                InitiativeRoleModel.name == "member",
            )
        )
    ).one()

    response = await client.put(
        a.g(f"/{_segment(tool)}/{entity.id}/grants"),
        headers=a.headers,
        json=[{"role_id": member_role.id, "level": "read"}],
    )
    assert response.status_code == 200, response.text
    grants = response.json()["grants"]
    assert [
        grant["level"] for grant in grants if grant["role_id"] == member_role.id
    ] == ["read"]


@pytest.mark.integration
@TOOLS
async def test_a_reader_cannot_reshare_it(
    client: AsyncClient, session: AsyncSession, acting_user, tool: Tool
):
    """Sharing is a write on the thing shared, so reading it is not enough."""
    a = await acting_user(guild_role=GuildRole.member, initiative=True)
    entity = await _entity(session, a, tool)
    b = await acting_user(
        guild_role=GuildRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )

    response = await client.put(
        b.g(f"/{_segment(tool)}/{entity.id}/grants"),
        headers=b.headers,
        json=[{"user_id": b.user.id, "level": "write"}],
    )
    assert response.status_code == 403, response.text


@pytest.mark.integration
@TOOLS
async def test_someone_outside_the_initiative_gets_the_tools_not_found(
    client: AsyncClient, session: AsyncSession, acting_user, tool: Tool
):
    """A guild member who is not in the initiative reaches none of its content,
    and the refusal is in the tool's own words."""
    a = await acting_user(guild_role=GuildRole.member, initiative=True)
    entity = await _entity(session, a, tool)
    outsider = await acting_user(guild_role=GuildRole.member, guild=a.guild)

    response = await client.put(
        outsider.g(f"/{_segment(tool)}/{entity.id}/grants"),
        headers=outsider.headers,
        json=[],
    )
    assert response.status_code == 404, response.text
    assert response.json()["detail"] == tool.not_found_code


@pytest.mark.integration
@TOOLS
async def test_the_room_is_told_that_sharing_moved(
    client: AsyncClient, session: AsyncSession, acting_user, tool: Tool, monkeypatch
):
    """Sharing decides who has the thing at all, so every open window is told
    and settles for itself what it may now see."""
    from app.services import stream_authz

    a = await acting_user(guild_role=GuildRole.member, initiative=True)
    entity = await _entity(session, a, tool)
    b = await acting_user(
        guild_role=GuildRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )

    emitted: list[tuple] = []

    async def _record(guild_id, resource_type, resource_id, event_type, data):
        emitted.append((guild_id, resource_type, resource_id, event_type, data))

    monkeypatch.setattr(stream_authz.authority, "emit", _record)

    response = await client.put(
        a.g(f"/{_segment(tool)}/{entity.id}/grants"),
        headers=a.headers,
        json=[{"user_id": b.user.id, "level": "write"}],
    )
    assert response.status_code == 200, response.text

    changed = [event for event in emitted if event[3] == "permissions_changed"]
    assert changed, emitted
    guild_id, resource_type, resource_id, _, data = changed[-1]
    assert (guild_id, resource_type, resource_id) == (a.guild.id, tool.value, entity.id)
    assert [
        grant["level"] for grant in data["grants"] if grant["user_id"] == b.user.id
    ] == ["write"]
