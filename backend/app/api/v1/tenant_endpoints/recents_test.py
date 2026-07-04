"""Integration tests for the polymorphic recent-items API.

Covers POST/DELETE ``/<entity>/{id}/view`` per type plus the combined
``GET /api/v1/recents`` endpoint that the layout tabs bar consumes.
"""

import asyncio

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.guild import GuildRole
from app.testing import (
    create_calendar_event,
    create_guild,
    create_guild_membership,
    create_project,
    create_queue,
)


@pytest.mark.integration
async def test_record_and_list_recent_project(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(guild_role=GuildRole.member, initiative=True)
    project = await create_project(session, a.initiative, a.user, name="P1")

    r = await client.post(a.g(f"/projects/{project.id}/view"), headers=a.headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["entity_type"] == "project"
    assert body["entity_id"] == project.id

    r = await client.get("/api/v1/recents/", headers=a.headers)
    assert r.status_code == 200
    items = r.json()
    assert len(items) == 1
    assert items[0]["entity_type"] == "project"
    assert items[0]["entity_id"] == project.id
    assert items[0]["name"] == "P1"


@pytest.mark.integration
async def test_record_and_list_recent_queue(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(guild_role=GuildRole.member, initiative=True)
    queue = await create_queue(session, a.initiative, a.user, name="Q1")

    r = await client.post(a.g(f"/queues/{queue.id}/view"), headers=a.headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["entity_type"] == "queue"
    assert body["entity_id"] == queue.id

    r = await client.get("/api/v1/recents/", headers=a.headers)
    assert r.status_code == 200
    items = r.json()
    assert any(
        i["entity_type"] == "queue" and i["entity_id"] == queue.id for i in items
    )


@pytest.mark.integration
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


@pytest.mark.integration
async def test_clear_view_removes_item(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(guild_role=GuildRole.member, initiative=True)
    project = await create_project(session, a.initiative, a.user, name="P")

    await client.post(a.g(f"/projects/{project.id}/view"), headers=a.headers)
    r = await client.delete(a.g(f"/projects/{project.id}/view"), headers=a.headers)
    assert r.status_code == 204

    r = await client.get("/api/v1/recents/", headers=a.headers)
    assert r.json() == []


@pytest.mark.integration
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


@pytest.mark.integration
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


@pytest.mark.integration
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


@pytest.mark.integration
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
        f"/api/v1/g/{a.guild.id}/recents/project/{project.id}",
        headers=a.headers,
    )
    assert r.status_code == 204

    r = await client.get("/api/v1/recents/", headers=a.headers)
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.integration
async def test_record_and_list_recent_calendar_event(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(guild_role=GuildRole.member, initiative=True)
    a.initiative.calendar_events_enabled = True
    session.add(a.initiative)
    await session.commit()
    event = await create_calendar_event(session, a.initiative, a.user, title="E1")

    r = await client.post(a.g(f"/calendar-events/{event.id}/view"), headers=a.headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["entity_type"] == "calendar_event"
    assert body["entity_id"] == event.id

    r = await client.get("/api/v1/recents/", headers=a.headers)
    assert r.status_code == 200
    items = r.json()
    assert any(
        i["entity_type"] == "calendar_event"
        and i["entity_id"] == event.id
        and i["name"] == "E1"
        for i in items
    )

    r = await client.delete(a.g(f"/calendar-events/{event.id}/view"), headers=a.headers)
    assert r.status_code == 204
    r = await client.get("/api/v1/recents/", headers=a.headers)
    assert all(i["entity_type"] != "calendar_event" for i in r.json())
