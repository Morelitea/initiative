"""Integration tests for the cross-guild recent-items bar.

Covers ``GET /api/v1/recents`` — the mixed-type list the layout header
consumes — and the guild-addressed delete that closes a tab. Recording and
forgetting a single entity is the per-tool pair, proved over the whole ``Tool``
enum in ``tool_views_test.py``.
"""

import asyncio

from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.guild import GuildRole
from app.testing import (
    create_calendar,
    create_guild,
    create_guild_membership,
    create_project,
    create_queue,
)


async def test_recents_mixed_ordering(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Items from different entity types must be ordered by last_viewed_at desc."""
    a = await acting_user(guild_role=GuildRole.member, initiative=True)
    project = await create_project(session, a.initiative, a.user, name="Older project")
    queue = await create_queue(session, a.initiative, a.user, name="Newer queue")

    r1 = await client.post(a.g(f"/projects/{project.id}/view"), headers=a.headers)
    assert r1.status_code == 200
    # Small delay so timestamps differ deterministically.
    await asyncio.sleep(0.05)
    r2 = await client.post(a.g(f"/queues/{queue.id}/view"), headers=a.headers)
    assert r2.status_code == 200

    r = await client.get("/api/v1/recents/", headers=a.headers)
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
    a = await acting_user(guild_role=GuildRole.member, initiative=True)
    project_a = await create_project(session, a.initiative, a.user, name="A's project")

    # The same user also belongs to a second guild.
    guild_b = await create_guild(session)
    await create_guild_membership(session, user=a.user, guild=guild_b)
    assert guild_b.id != a.guild.id

    # A different member of guild A.
    other = await acting_user(
        guild_role=GuildRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )

    # Record the view while in guild A...
    r = await client.post(a.g(f"/projects/{project_a.id}/view"), headers=a.headers)
    assert r.status_code == 200

    # ...then enter guild B: the tab still renders (name + owning guild).
    r = await client.get("/api/v1/recents/", headers=a.headers)
    assert r.status_code == 200
    items = r.json()
    assert [(i["entity_type"], i["entity_id"], i["guild_id"]) for i in items] == [
        ("project", project_a.id, a.guild.id)
    ]
    assert items[0]["name"] == "A's project"

    # The list is the user's own: another member of guild A sees nothing.
    r = await client.get("/api/v1/recents/", headers=other.headers)
    assert r.status_code == 200
    assert r.json() == []


async def test_recent_tabs_limit_caps_list_and_prune(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The user's ``recent_tabs_limit`` bounds both what's stored (prune) and
    what the tabs-bar endpoint returns."""
    a = await acting_user(guild_role=GuildRole.member, initiative=True)

    # Lower the user's recents cap to 2 via self-update.
    r = await client.patch(
        "/api/v1/users/me", json={"recent_tabs_limit": 2}, headers=a.headers
    )
    assert r.status_code == 200, r.text
    assert r.json()["recent_tabs_limit"] == 2

    # Open four projects, oldest first.
    projects = [
        await create_project(session, a.initiative, a.user, name=f"P{i}")
        for i in range(4)
    ]
    for project in projects:
        rv = await client.post(a.g(f"/projects/{project.id}/view"), headers=a.headers)
        assert rv.status_code == 200
        await asyncio.sleep(0.02)

    # Only the two most-recently-opened survive — the rest were pruned.
    r = await client.get("/api/v1/recents/", headers=a.headers)
    assert r.status_code == 200
    items = r.json()
    assert [i["entity_id"] for i in items] == [projects[3].id, projects[2].id]


async def test_recent_tabs_limit_rejects_out_of_range(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The cap is validated to [1, 100]."""
    a = await acting_user(guild_role=GuildRole.member, initiative=True)

    r = await client.patch(
        "/api/v1/users/me", json={"recent_tabs_limit": 0}, headers=a.headers
    )
    assert r.status_code == 422
    r = await client.patch(
        "/api/v1/users/me", json={"recent_tabs_limit": 101}, headers=a.headers
    )
    assert r.status_code == 422


async def test_clear_recent_is_guild_addressed(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Closing a tab works from any context via the guild path segment."""
    a = await acting_user(guild_role=GuildRole.member, initiative=True)
    project = await create_project(session, a.initiative, a.user, name="P")

    other_guild = await create_guild(session)
    await create_guild_membership(session, user=a.user, guild=other_guild)

    await client.post(a.g(f"/projects/{project.id}/view"), headers=a.headers)

    # Close guild A's tab while in guild B — addressed by the guild path.
    r = await client.delete(
        f"/api/v1/c/{a.guild.id}/recents/project/{project.id}",
        headers=a.headers,
    )
    assert r.status_code == 204

    r = await client.get("/api/v1/recents/", headers=a.headers)
    assert r.status_code == 200
    assert r.json() == []


async def test_recent_guild_level_calendar_has_no_initiative(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """A guild-level calendar reports ``initiative_id: None`` — the tabs bar
    reads that as "address me at the guild route", not as missing data."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    a.initiative.calendars_enabled = True
    session.add(a.initiative)
    await session.commit()
    calendar = await create_calendar(session, a.initiative, a.user, name="GuildCal")
    calendar.initiative_id = None
    session.add(calendar)
    await session.commit()

    r = await client.post(a.g(f"/calendars/{calendar.id}/view"), headers=a.headers)
    assert r.status_code == 200, r.text

    r = await client.get("/api/v1/recents/", headers=a.headers)
    assert r.status_code == 200
    row = next(i for i in r.json() if i["entity_id"] == calendar.id)
    assert row["initiative_id"] is None
