"""Integration tests for the cross-guild recent-items bar.

Covers ``GET /api/v1/recents`` — the mixed-type list the layout header
consumes — and the guild-addressed pair that opens and closes a tab. Opening
one is proved over the whole ``Tool`` enum, so a new tool is exercised here
the moment it exists.
"""

import asyncio

import pytest
from httpx import AsyncClient
from sqlalchemy.exc import DBAPIError
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.tools import Tool
from app.models.platform.guild import CommunityRole
from app.models.tenant.project import Project
from app.models.tenant.recent_view import RecentView
from app.models.tenant.resource_grant import ResourceAccessLevel
from app.testing import (
    create_calendar,
    create_guild,
    create_guild_membership,
    create_project,
    create_queue,
    create_resource_grant,
    create_tool_entity,
    enable_all_tools,
    route_as,
)

RECENTS = "/api/v1/recents/"

#: Every tool, as its own test case.
TOOLS = pytest.mark.parametrize("tool", list(Tool), ids=[t.value for t in Tool])


async def test_recents_mixed_ordering(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Items from different entity types must be ordered by last_viewed_at desc."""
    a = await acting_user(guild_role=CommunityRole.member, initiative=True)
    project = await create_project(session, a.initiative, a.user, name="Older project")
    queue = await create_queue(session, a.initiative, a.user, name="Newer queue")

    r1 = await client.post(a.g(f"/recents/project/{project.id}"), headers=a.headers)
    assert r1.status_code == 200
    # Small delay so timestamps differ deterministically.
    await asyncio.sleep(0.05)
    r2 = await client.post(a.g(f"/recents/queue/{queue.id}"), headers=a.headers)
    assert r2.status_code == 200

    r = await client.get(RECENTS, headers=a.headers)
    items = r.json()
    # Newer queue must come first.
    assert items[0]["entity_type"] == "queue"
    assert items[0]["entity_id"] == queue.id
    assert items[1]["entity_type"] == "project"
    assert items[1]["entity_id"] == project.id


async def test_recents_are_cross_guild_names_only(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The tabs bar shows entities from ANY of the user's guilds, from any
    context — render metadata only, tagged with the owning guild. Another
    user never sees them."""
    a = await acting_user(guild_role=CommunityRole.member, initiative=True)
    project_a = await create_project(session, a.initiative, a.user, name="A's project")

    # The same user also belongs to a second guild.
    guild_b = await create_guild(session)
    await create_guild_membership(session, user=a.user, guild=guild_b)
    assert guild_b.id != a.guild.id

    # A different member of guild A.
    other = await acting_user(
        guild_role=CommunityRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )

    # Record the view while in guild A...
    r = await client.post(a.g(f"/recents/project/{project_a.id}"), headers=a.headers)
    assert r.status_code == 200

    # ...then enter guild B: the tab still renders (name + owning guild).
    r = await client.get(RECENTS, headers=a.headers)
    assert r.status_code == 200
    items = r.json()
    assert [(i["entity_type"], i["entity_id"], i["community_id"]) for i in items] == [
        ("project", project_a.id, a.guild.id)
    ]
    assert items[0]["name"] == "A's project"

    # The list is the user's own: another member of guild A sees nothing.
    r = await client.get(RECENTS, headers=other.headers)
    assert r.status_code == 200
    assert r.json() == []


async def test_a_recent_view_is_its_owners_row(
    client: AsyncClient, session: AsyncSession, acting_user, role_session
):
    """Another member who can edit the same project neither reads nor writes
    someone's recent view of it in the database; the community's admin
    reads it, which a purge of the project needs."""
    a = await acting_user(guild_role=CommunityRole.member, initiative=True)
    project = await create_project(session, a.initiative, a.user)
    other = await acting_user(
        guild_role=CommunityRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )
    await create_resource_grant(
        session, project, user=other.user, level=ResourceAccessLevel.write
    )
    admin = await acting_user(guild_role=CommunityRole.admin, guild=a.guild)
    r = await client.post(a.g(f"/recents/project/{project.id}"), headers=a.headers)
    assert r.status_code == 200

    asking = await role_session("app_user")
    await route_as(asking, user_id=other.user.id, guild_id=a.guild.id)
    assert (await asking.exec(select(Project.id))).all() == [project.id]
    assert (await asking.exec(select(RecentView))).all() == []
    asking.add(
        RecentView(user_id=a.user.id, entity_type="project", entity_id=project.id)
    )
    with pytest.raises(DBAPIError, match="row-level security"):
        await asking.flush()

    asking = await role_session("app_user")
    await route_as(asking, user_id=admin.user.id, guild_id=a.guild.id)
    seen = (await asking.exec(select(RecentView.user_id))).all()
    assert seen == [a.user.id]


async def test_recent_tabs_limit_caps_list_and_prune(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The user's ``recent_tabs_limit`` bounds both what's stored (prune) and
    what the tabs-bar endpoint returns."""
    a = await acting_user(guild_role=CommunityRole.member, initiative=True)

    # Lower the user's recents cap to 2 via self-update.
    r = await client.patch(
        "/api/v1/me", json={"recent_tabs_limit": 2}, headers=a.headers
    )
    assert r.status_code == 200, r.text
    assert r.json()["recent_tabs_limit"] == 2

    # Open four projects, oldest first.
    projects = [
        await create_project(session, a.initiative, a.user, name=f"P{i}")
        for i in range(4)
    ]
    for project in projects:
        rv = await client.post(a.g(f"/recents/project/{project.id}"), headers=a.headers)
        assert rv.status_code == 200
        await asyncio.sleep(0.02)

    # Only the two most-recently-opened survive — the rest were pruned.
    r = await client.get(RECENTS, headers=a.headers)
    assert r.status_code == 200
    items = r.json()
    assert [i["entity_id"] for i in items] == [projects[3].id, projects[2].id]


async def test_recent_tabs_limit_rejects_out_of_range(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The cap is validated to [1, 100]."""
    a = await acting_user(guild_role=CommunityRole.member, initiative=True)

    r = await client.patch(
        "/api/v1/me", json={"recent_tabs_limit": 0}, headers=a.headers
    )
    assert r.status_code == 422
    r = await client.patch(
        "/api/v1/me", json={"recent_tabs_limit": 101}, headers=a.headers
    )
    assert r.status_code == 422


async def test_clear_recent_is_guild_addressed(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Closing a tab works from any context via the guild path segment."""
    a = await acting_user(guild_role=CommunityRole.member, initiative=True)
    project = await create_project(session, a.initiative, a.user, name="P")

    other_guild = await create_guild(session)
    await create_guild_membership(session, user=a.user, guild=other_guild)

    await client.post(a.g(f"/recents/project/{project.id}"), headers=a.headers)

    # Close guild A's tab while in guild B — addressed by the guild path.
    r = await client.delete(
        f"/api/v1/c/{a.guild.id}/recents/project/{project.id}",
        headers=a.headers,
    )
    assert r.status_code == 204

    r = await client.get(RECENTS, headers=a.headers)
    assert r.status_code == 200
    assert r.json() == []


async def test_recent_guild_level_calendar_has_no_initiative(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """A guild-level calendar reports ``initiative_id: None`` — the tabs bar
    reads that as "address me at the guild route", not as missing data."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    a.initiative.calendars_enabled = True
    session.add(a.initiative)
    await session.commit()
    calendar = await create_calendar(session, a.initiative, a.user, name="GuildCal")
    calendar.initiative_id = None
    session.add(calendar)
    await session.commit()

    r = await client.post(a.g(f"/recents/calendar/{calendar.id}"), headers=a.headers)
    assert r.status_code == 200, r.text

    r = await client.get(RECENTS, headers=a.headers)
    assert r.status_code == 200
    row = next(i for i in r.json() if i["entity_id"] == calendar.id)
    assert row["initiative_id"] is None


@TOOLS
async def test_opening_a_tab_puts_the_tool_in_the_tabs_bar(
    client: AsyncClient, session: AsyncSession, acting_user, tool: Tool
):
    """Recording a view reads the entity as its own page does, and a guild
    member outside the initiative is refused in the tool's own words."""
    a = await acting_user(guild_role=CommunityRole.member, initiative=True)
    await enable_all_tools(session, a.initiative)
    entity = await create_tool_entity(session, tool, a.initiative, a.user)

    response = await client.post(
        a.g(f"/recents/{tool.value}/{entity.id}"), headers=a.headers
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["entity_type"], body["entity_id"]) == (tool.value, entity.id)
    assert body["last_viewed_at"]

    listed = await client.get(RECENTS, headers=a.headers)
    assert listed.status_code == 200, listed.text
    assert [(i["entity_type"], i["entity_id"]) for i in listed.json()] == [
        (tool.value, entity.id)
    ]

    outsider = await acting_user(guild_role=CommunityRole.member, guild=a.guild)
    refused = await client.post(
        outsider.g(f"/recents/{tool.value}/{entity.id}"), headers=outsider.headers
    )
    assert refused.status_code == 404, refused.text
    assert refused.json()["detail"] == tool.not_found_code
    assert (await client.get(RECENTS, headers=outsider.headers)).json() == []
