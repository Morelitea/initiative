"""Integration tests for the polymorphic recent-items API.

Covers POST/DELETE ``/<entity>/{id}/view`` per type plus the combined
``GET /api/v1/recents`` endpoint that the layout tabs bar consumes.
"""

import asyncio

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.testing.factories import (
    create_guild,
    create_guild_membership,
    create_initiative,
    create_project,
    create_queue,
    create_user,
    get_guild_headers,
)


async def _make_user_with_guild_and_initiative(session, email="user@example.com"):
    user = await create_user(session, email=email)
    guild = await create_guild(session)
    await create_guild_membership(session, user=user, guild=guild)
    initiative = await create_initiative(session, guild, user, name="Init")
    return user, guild, initiative


@pytest.mark.integration
async def test_record_and_list_recent_project(
    client: AsyncClient, session: AsyncSession
):
    user, guild, initiative = await _make_user_with_guild_and_initiative(session)
    project = await create_project(session, initiative, user, name="P1")

    headers = await get_guild_headers(session, guild, user)

    r = await client.post(
        f"/api/v1/g/{guild.id}/projects/{project.id}/view", headers=headers
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["entity_type"] == "project"
    assert body["entity_id"] == project.id

    r = await client.get("/api/v1/recents/", headers=headers)
    assert r.status_code == 200
    items = r.json()
    assert len(items) == 1
    assert items[0]["entity_type"] == "project"
    assert items[0]["entity_id"] == project.id
    assert items[0]["name"] == "P1"


@pytest.mark.integration
async def test_record_and_list_recent_queue(client: AsyncClient, session: AsyncSession):
    user, guild, initiative = await _make_user_with_guild_and_initiative(
        session, email="queue@example.com"
    )
    queue = await create_queue(session, initiative, user, name="Q1")

    headers = await get_guild_headers(session, guild, user)

    r = await client.post(
        f"/api/v1/g/{guild.id}/queues/{queue.id}/view", headers=headers
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["entity_type"] == "queue"
    assert body["entity_id"] == queue.id

    r = await client.get("/api/v1/recents/", headers=headers)
    assert r.status_code == 200
    items = r.json()
    assert any(
        i["entity_type"] == "queue" and i["entity_id"] == queue.id for i in items
    )


@pytest.mark.integration
async def test_recents_mixed_ordering(client: AsyncClient, session: AsyncSession):
    """Items from different entity types must be ordered by last_viewed_at desc."""
    user, guild, initiative = await _make_user_with_guild_and_initiative(
        session, email="mix@example.com"
    )
    project = await create_project(session, initiative, user, name="Older project")
    queue = await create_queue(session, initiative, user, name="Newer queue")

    headers = await get_guild_headers(session, guild, user)

    r1 = await client.post(
        f"/api/v1/g/{guild.id}/projects/{project.id}/view", headers=headers
    )
    assert r1.status_code == 200
    # Small delay so timestamps differ deterministically.
    await asyncio.sleep(0.05)
    r2 = await client.post(
        f"/api/v1/g/{guild.id}/queues/{queue.id}/view", headers=headers
    )
    assert r2.status_code == 200

    r = await client.get("/api/v1/recents/", headers=headers)
    items = r.json()
    # Newer queue must come first.
    assert items[0]["entity_type"] == "queue"
    assert items[0]["entity_id"] == queue.id
    assert items[1]["entity_type"] == "project"
    assert items[1]["entity_id"] == project.id


@pytest.mark.integration
async def test_clear_view_removes_item(client: AsyncClient, session: AsyncSession):
    user, guild, initiative = await _make_user_with_guild_and_initiative(
        session, email="clear@example.com"
    )
    project = await create_project(session, initiative, user, name="P")
    headers = await get_guild_headers(session, guild, user)

    await client.post(
        f"/api/v1/g/{guild.id}/projects/{project.id}/view", headers=headers
    )
    r = await client.delete(
        f"/api/v1/g/{guild.id}/projects/{project.id}/view", headers=headers
    )
    assert r.status_code == 204

    r = await client.get("/api/v1/recents/", headers=headers)
    assert r.json() == []


@pytest.mark.integration
async def test_recents_are_cross_guild_names_only(
    client: AsyncClient, session: AsyncSession
):
    """The tabs bar shows entities from ANY of the user's guilds, from any
    context — render metadata only, tagged with the owning guild. Another
    user never sees them."""
    user = await create_user(session, email="multi@example.com")

    guild_a = await create_guild(session)
    await create_guild_membership(session, user=user, guild=guild_a)
    init_a = await create_initiative(session, guild_a, user, name="A")
    project_a = await create_project(session, init_a, user, name="A's project")

    guild_b = await create_guild(session)
    await create_guild_membership(session, user=user, guild=guild_b)

    other = await create_user(session, email="other-multi@example.com")
    await create_guild_membership(session, user=other, guild=guild_a)

    # Record the view while in guild A...
    headers = await get_guild_headers(session, guild_a, user)
    r = await client.post(
        f"/api/v1/g/{guild_a.id}/projects/{project_a.id}/view", headers=headers
    )
    assert r.status_code == 200

    # ...then enter guild B: the tab still renders (name + owning guild).
    headers = await get_guild_headers(session, guild_b, user)
    r = await client.get("/api/v1/recents/", headers=headers)
    assert r.status_code == 200
    items = r.json()
    assert [(i["entity_type"], i["entity_id"], i["guild_id"]) for i in items] == [
        ("project", project_a.id, guild_a.id)
    ]
    assert items[0]["name"] == "A's project"

    # The list is the user's own: another member of guild A sees nothing.
    other_headers = await get_guild_headers(session, guild_a, other)
    r = await client.get("/api/v1/recents/", headers=other_headers)
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.integration
async def test_clear_recent_is_guild_addressed(
    client: AsyncClient, session: AsyncSession
):
    """Closing a tab works from any context via the guild path segment."""
    user, guild, initiative = await _make_user_with_guild_and_initiative(
        session, email="close-tab@example.com"
    )
    project = await create_project(session, initiative, user, name="P")
    other_guild = await create_guild(session)
    await create_guild_membership(session, user=user, guild=other_guild)

    headers = await get_guild_headers(session, guild, user)
    await client.post(
        f"/api/v1/g/{guild.id}/projects/{project.id}/view", headers=headers
    )

    headers = await get_guild_headers(session, other_guild, user)

    # Close guild A's tab while in guild B — addressed by the guild path.
    r = await client.delete(
        f"/api/v1/g/{guild.id}/recents/project/{project.id}",
        headers=headers,
    )
    assert r.status_code == 204

    r = await client.get("/api/v1/recents/", headers=headers)
    assert r.status_code == 200
    assert r.json() == []
