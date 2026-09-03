"""Integration tests for the cross-guild tool lists behind the My Tools page.

Covers ``GET /api/v1/me/{queues,counter-groups,dashboards}`` and
``GET /api/v1/me/tools/counts``: what reaches the caller across their
communities, the made-by-me view, and the guild boundary.
"""

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.guild import GuildRole
from app.testing import (
    Actor,
    create_guild,
    create_guild_membership,
    create_initiative,
)


async def _enable_tools(client, actor):
    """Turn on the toggleable tools for the actor's initiative."""
    response = await client.patch(
        actor.g(f"/initiatives/{actor.initiative.id}"),
        headers=actor.headers,
        json={
            "queues_enabled": True,
            "counter_groups_enabled": True,
            "dashboards_enabled": True,
        },
    )
    assert response.status_code == 200, response.text


async def _create_queue(client, actor, name="Queue"):
    response = await client.post(
        actor.g("/queues/"),
        headers=actor.headers,
        json={"name": name, "initiative_id": actor.initiative.id},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _create_counter_group(client, actor, name="Counters"):
    response = await client.post(
        actor.g("/counter-groups/"),
        headers=actor.headers,
        json={"name": name, "initiative_id": actor.initiative.id},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _create_dashboard(client, actor, name="Dashboard"):
    response = await client.post(
        actor.g("/dashboards/"),
        headers=actor.headers,
        json={"name": name, "initiative_id": actor.initiative.id},
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.integration
async def test_list_my_queues(client: AsyncClient, acting_user):
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _enable_tools(client, a)
    queue = await _create_queue(client, a, "Standup")

    response = await client.get("/api/v1/me/queues", headers=a.headers)

    assert response.status_code == 200
    data = response.json()
    assert queue["id"] in {q["id"] for q in data["items"]}
    assert data["total_count"] >= 1


@pytest.mark.integration
async def test_list_my_counter_groups_and_dashboards(client: AsyncClient, acting_user):
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _enable_tools(client, a)
    group = await _create_counter_group(client, a, "Scores")
    dashboard = await _create_dashboard(client, a, "Overview")

    groups = await client.get("/api/v1/me/counter-groups", headers=a.headers)
    assert groups.status_code == 200
    assert group["id"] in {g["id"] for g in groups.json()["items"]}

    dashboards = await client.get("/api/v1/me/dashboards", headers=a.headers)
    assert dashboards.status_code == 200
    assert dashboard["id"] in {d["id"] for d in dashboards.json()["items"]}


@pytest.mark.integration
async def test_list_my_queues_excludes_other_guilds(client: AsyncClient, acting_user):
    """A guild the caller does not belong to contributes nothing."""
    outsider = await acting_user(guild_role=GuildRole.admin, initiative=True)
    stranger = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _enable_tools(client, stranger)
    stranger_queue = await _create_queue(client, stranger, "Not Yours")

    response = await client.get("/api/v1/me/queues", headers=outsider.headers)

    assert response.status_code == 200
    keyed = {(q["guild_id"], q["id"]) for q in response.json()["items"]}
    assert (stranger.guild.id, stranger_queue["id"]) not in keyed


@pytest.mark.integration
async def test_list_my_queues_created_by_me(client: AsyncClient, acting_user):
    """The made-by-me view keeps only what the caller wrote."""
    admin = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _enable_tools(client, admin)
    other = await acting_user(
        guild_role=GuildRole.member,
        guild=admin.guild,
        initiative=admin.initiative,
        initiative_role="member",
    )

    admin_queue = await _create_queue(client, admin, "Admin's Queue")

    everything = await client.get("/api/v1/me/queues", headers=other.headers)
    assert everything.status_code == 200
    assert admin_queue["id"] in {q["id"] for q in everything.json()["items"]}

    mine = await client.get(
        "/api/v1/me/queues?created_by_me=true", headers=other.headers
    )
    assert mine.status_code == 200
    assert admin_queue["id"] not in {q["id"] for q in mine.json()["items"]}


@pytest.mark.integration
async def test_list_my_queues_guild_filter(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """``guild_ids`` narrows the merge to a subset of the caller's guilds."""
    a1 = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _enable_tools(client, a1)
    user = a1.user

    guild2 = await create_guild(session, creator=user, name="Second Guild")
    await create_guild_membership(
        session, user=user, guild=guild2, role=GuildRole.admin
    )
    init2 = await create_initiative(session, guild2, user, name="Initiative")
    a2 = Actor(user=user, headers=a1.headers, guild=guild2, initiative=init2)
    await _enable_tools(client, a2)

    queue1 = await _create_queue(client, a1, "Queue in Guild 1")
    queue2 = await _create_queue(client, a2, "Queue in Guild 2")

    def keyed(resp):
        return {(q["guild_id"], q["id"]) for q in resp.json()["items"]}

    both = await client.get("/api/v1/me/queues", headers=a1.headers)
    assert both.status_code == 200
    assert (a1.guild.id, queue1["id"]) in keyed(both)
    assert (guild2.id, queue2["id"]) in keyed(both)

    narrowed = await client.get(
        f"/api/v1/me/queues?guild_ids={a1.guild.id}", headers=a1.headers
    )
    assert narrowed.status_code == 200
    assert (a1.guild.id, queue1["id"]) in keyed(narrowed)
    assert (guild2.id, queue2["id"]) not in keyed(narrowed)


@pytest.mark.integration
async def test_list_my_queues_hidden_when_tool_disabled(
    client: AsyncClient, acting_user
):
    """A queue in an initiative with the tool switched off is not listed."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _enable_tools(client, a)
    queue = await _create_queue(client, a, "Switched Off Later")

    response = await client.patch(
        a.g(f"/initiatives/{a.initiative.id}"),
        headers=a.headers,
        json={"queues_enabled": False},
    )
    assert response.status_code == 200

    response = await client.get("/api/v1/me/queues", headers=a.headers)
    assert response.status_code == 200
    assert queue["id"] not in {q["id"] for q in response.json()["items"]}


@pytest.mark.integration
async def test_list_my_queues_pagination(client: AsyncClient, acting_user):
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _enable_tools(client, a)
    for index in range(3):
        await _create_queue(client, a, f"Queue {index}")

    first = await client.get("/api/v1/me/queues?page=1&page_size=2", headers=a.headers)
    assert first.status_code == 200
    assert len(first.json()["items"]) == 2
    assert first.json()["total_count"] == 3
    assert first.json()["has_next"] is True

    second = await client.get("/api/v1/me/queues?page=2&page_size=2", headers=a.headers)
    assert second.status_code == 200
    assert len(second.json()["items"]) == 1
    assert second.json()["has_next"] is False


@pytest.mark.integration
async def test_my_tool_counts(client: AsyncClient, acting_user):
    """Every tool is answered for, with a zero where the caller has none."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _enable_tools(client, a)
    await _create_queue(client, a, "Standup")
    await _create_queue(client, a, "Retro")

    response = await client.get("/api/v1/me/tools/counts", headers=a.headers)

    assert response.status_code == 200
    counts = response.json()["counts"]
    assert counts["queue"] == 2
    # Present rather than absent: the page needs "none" to be distinguishable
    # from "not asked" when it decides which tabs to draw.
    assert counts["counter_group"] == 0
    assert set(counts) == {
        "project",
        "document",
        "queue",
        "counter_group",
        "calendar",
        "dashboard",
    }


@pytest.mark.integration
async def test_my_tool_counts_created_by_me(client: AsyncClient, acting_user):
    """The counts follow the view the page is in."""
    admin = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _enable_tools(client, admin)
    other = await acting_user(
        guild_role=GuildRole.member,
        guild=admin.guild,
        initiative=admin.initiative,
        initiative_role="member",
    )
    await _create_queue(client, admin, "Admin's Queue")

    everything = await client.get("/api/v1/me/tools/counts", headers=other.headers)
    assert everything.status_code == 200
    assert everything.json()["counts"]["queue"] == 1

    mine = await client.get(
        "/api/v1/me/tools/counts?created_by_me=true", headers=other.headers
    )
    assert mine.status_code == 200
    assert mine.json()["counts"]["queue"] == 0
