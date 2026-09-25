"""Integration tests for the cross-guild tool lists behind the My Tools page.

``GET /api/v1/me/{tool}`` is one route mounted per tool out of
``MY_TOOL_LISTS``, so the proofs that hold for every tool are parametrised
over the ``Tool`` enum rather than written per tool. What belongs to one tool
— a guild calendar, a project's archive — keeps its own case below.

``GET /api/v1/me/tools/counts``, which is what decides the page's tabs, is at
the end.
"""

from datetime import datetime, timezone

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.tools import Tool
from app.models.platform.guild import GuildRole
from app.testing import (
    strip_non_owner_grants,
    Actor,
    create_calendar,
    create_guild,
    create_guild_calendar,
    create_guild_membership,
    create_initiative,
    create_initiative_member,
    create_project,
    create_tool_entity,
    create_user,
    get_auth_headers,
)
from app.services.tenant.my_tools import tool_model

per_tool = pytest.mark.parametrize("tool", list(Tool), ids=lambda t: t.value)


def _path(tool: Tool) -> str:
    """The cross-guild list route for a tool."""
    return f"/api/v1/me/{tool.route_segment}"


def _keyed(response) -> set[tuple[int, int]]:
    """Items keyed by (guild, id): per-schema ids collide across communities,
    which is what callers of a merged list must key by too."""
    return {(item["guild_id"], item["id"]) for item in response.json()["items"]}


async def _enable_tools(client, actor):
    """Turn on every tool for the actor's initiative."""
    response = await client.patch(
        actor.g(f"/initiatives/{actor.initiative.id}"),
        headers=actor.headers,
        json={tool.view_permission: True for tool in Tool},
    )
    assert response.status_code == 200, response.text


async def _create(client, actor, tool: Tool, name: str) -> dict:
    """Make one of ``tool`` in the actor's initiative, through its own route.

    Every tool is created the same way — a name and the initiative that holds
    it — so the route is derived from the enum rather than listed per tool.
    """
    response = await client.post(
        actor.g(f"/{tool.route_segment}/"),
        headers=actor.headers,
        json={"name": name, "initiative_id": actor.initiative.id},
    )
    assert response.status_code == 201, response.text
    return response.json()


# ---------------------------------------------------------------------------
# What every tool's list does
# ---------------------------------------------------------------------------


@per_tool
async def test_the_list_answers_with_what_reaches_the_caller(
    client: AsyncClient, acting_user, tool: Tool
):
    """The row a caller just made is in their cross-guild list for that tool."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _enable_tools(client, a)
    row = await _create(client, a, tool, "Standup")

    response = await client.get(_path(tool), headers=a.headers)

    assert response.status_code == 200
    data = response.json()
    assert row["id"] in {item["id"] for item in data["items"]}
    assert data["total_count"] >= 1


@per_tool
async def test_a_guild_the_caller_is_not_in_contributes_nothing(
    client: AsyncClient, acting_user, tool: Tool
):
    """The merge visits the caller's own communities and no others."""
    outsider = await acting_user(guild_role=GuildRole.admin, initiative=True)
    stranger = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _enable_tools(client, stranger)
    theirs = await _create(client, stranger, tool, "Not Yours")

    response = await client.get(_path(tool), headers=outsider.headers)

    assert response.status_code == 200
    assert (stranger.guild.id, theirs["id"]) not in _keyed(response)


@per_tool
async def test_created_by_me_keeps_only_what_the_caller_wrote(
    client: AsyncClient, acting_user, tool: Tool
):
    """The page's other view: authorship, not everything that reaches you."""
    admin = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _enable_tools(client, admin)
    other = await acting_user(
        guild_role=GuildRole.member,
        guild=admin.guild,
        initiative=admin.initiative,
        initiative_role="member",
    )
    theirs = await _create(client, admin, tool, "Admin's")

    everything = await client.get(_path(tool), headers=other.headers)
    assert everything.status_code == 200
    assert theirs["id"] in {item["id"] for item in everything.json()["items"]}

    mine = await client.get(f"{_path(tool)}?created_by_me=true", headers=other.headers)
    assert mine.status_code == 200
    assert theirs["id"] not in {item["id"] for item in mine.json()["items"]}


@per_tool
async def test_guild_ids_narrows_the_merge(
    client: AsyncClient, session: AsyncSession, acting_user, tool: Tool
):
    """Unfiltered the list spans every community the caller belongs to;
    ``guild_ids`` narrows it to the ones named."""
    a1 = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _enable_tools(client, a1)
    user = a1.user

    guild2 = await create_guild(session, creator=user, name="Second Guild")
    await create_guild_membership(
        session, user=user, guild=guild2, role=GuildRole.admin
    )
    init2 = await create_initiative(session, guild2, user, name="Initiative")
    # A second actor view for the SAME user bound to guild2, so a2.g() addresses
    # guild2 while a2.headers is still the user's auth.
    a2 = Actor(user=user, headers=a1.headers, guild=guild2, initiative=init2)
    await _enable_tools(client, a2)

    row1 = await _create(client, a1, tool, "In Guild 1")
    row2 = await _create(client, a2, tool, "In Guild 2")

    both = await client.get(_path(tool), headers=a1.headers)
    assert both.status_code == 200
    assert (a1.guild.id, row1["id"]) in _keyed(both)
    assert (guild2.id, row2["id"]) in _keyed(both)

    narrowed = await client.get(
        f"{_path(tool)}?guild_ids={a1.guild.id}", headers=a1.headers
    )
    assert narrowed.status_code == 200
    assert (a1.guild.id, row1["id"]) in _keyed(narrowed)
    assert (guild2.id, row2["id"]) not in _keyed(narrowed)


@per_tool
async def test_search_narrows_by_name(client: AsyncClient, acting_user, tool: Tool):
    """The filter box reads the same index the search page does."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _enable_tools(client, a)
    alpha = await _create(client, a, tool, "Alpha Notes")
    beta = await _create(client, a, tool, "Beta Summary")

    response = await client.get(f"{_path(tool)}?search=alpha", headers=a.headers)

    assert response.status_code == 200
    found = {item["id"] for item in response.json()["items"]}
    assert alpha["id"] in found
    assert beta["id"] not in found


@per_tool
async def test_pagination_walks_the_merged_list(
    client: AsyncClient, acting_user, tool: Tool
):
    """Slicing happens over the merged list, since per-schema SQL can't."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _enable_tools(client, a)
    for index in range(3):
        await _create(client, a, tool, f"Row {index}")

    first = await client.get(f"{_path(tool)}?page=1&page_size=2", headers=a.headers)
    assert first.status_code == 200
    assert len(first.json()["items"]) == 2
    assert first.json()["total_count"] == 3
    assert first.json()["has_next"] is True

    second = await client.get(f"{_path(tool)}?page=2&page_size=2", headers=a.headers)
    assert second.status_code == 200
    assert len(second.json()["items"]) == 1
    assert second.json()["has_next"] is False


@per_tool
async def test_the_initiatives_switch_takes_a_row_off_the_list(
    client: AsyncClient, acting_user, tool: Tool
):
    """A row in an initiative with its tool switched off is not listed."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _enable_tools(client, a)
    row = await _create(client, a, tool, "Switched Off Later")

    response = await client.patch(
        a.g(f"/initiatives/{a.initiative.id}"),
        headers=a.headers,
        json={tool.view_permission: False},
    )
    assert response.status_code == 200

    response = await client.get(_path(tool), headers=a.headers)
    assert response.status_code == 200
    assert row["id"] not in {item["id"] for item in response.json()["items"]}


async def test_a_co_member_reads_what_was_shared_with_the_initiative(
    client: AsyncClient, acting_user
):
    """Sharing is what the list answers by, not who made the row."""
    admin = await acting_user(guild_role=GuildRole.admin, initiative=True)
    other = await acting_user(
        guild_role=GuildRole.member,
        guild=admin.guild,
        initiative=admin.initiative,
        initiative_role="member",
    )
    # Created through the API, so it carries the default all-members read grant.
    admin_doc = await _create(client, admin, Tool.document, "Admin's Doc")

    response = await client.get("/api/v1/me/documents", headers=other.headers)

    assert response.status_code == 200
    assert admin_doc["id"] in {d["id"] for d in response.json()["items"]}


# ---------------------------------------------------------------------------
# What belongs to one tool
# ---------------------------------------------------------------------------


async def test_my_projects_excludes_archived(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Archived work is off the working list."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    live = await create_project(session, a.initiative, a.user, name="Project")
    archived = await create_project(session, a.initiative, a.user, name="Archived")
    archived.archived_at = datetime.now(timezone.utc)
    session.add(archived)
    await session.commit()

    response = await client.get("/api/v1/me/projects", headers=a.headers)

    assert response.status_code == 200
    project_ids = {p["id"] for p in response.json()["items"]}
    assert live.id in project_ids
    assert archived.id not in project_ids


@pytest.mark.parametrize(
    "tool",
    [t for t in Tool if "is_template" in tool_model(t).model_fields],
    ids=lambda t: t.value,
)
async def test_my_tools_exclude_templates(
    client: AsyncClient, session: AsyncSession, acting_user, tool: Tool
):
    """A blueprint is a tool's own second state, and not work — for every tool
    whose model carries one."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    live = await create_tool_entity(session, tool, a.initiative, a.user, name="Live")
    template = await create_tool_entity(
        session, tool, a.initiative, a.user, name="Template", is_template=True
    )

    response = await client.get(_path(tool), headers=a.headers)

    assert response.status_code == 200
    ids = {row["id"] for row in response.json()["items"]}
    assert live.id in ids
    assert template.id not in ids


async def test_my_projects_follows_grants_not_guild_admin_standing(
    client: AsyncClient, session: AsyncSession
):
    """A guild admin's My Projects is what has been shared with them.

    Their authority still reaches every project in the community — asking for
    the initiative by name still answers with all of it. A list that spans
    initiatives answers a different question: what reaches the reader.
    """
    owner = await create_user(session, email="owner@example.com")
    admin = await create_user(session, email="otheradmin@example.com")

    guild = await create_guild(session, creator=owner, name="Shared Guild")
    await create_guild_membership(
        session, user=owner, guild=guild, role=GuildRole.admin
    )
    await create_guild_membership(
        session, user=admin, guild=guild, role=GuildRole.admin
    )

    elsewhere = await create_initiative(session, guild, owner, name="Not Theirs")
    unshared = await create_project(session, elsewhere, owner, name="Someone Else's")

    mine = await create_initiative(session, guild, admin, name="Theirs")
    shared = await create_project(session, mine, admin, name="Their Own")

    response = await client.get("/api/v1/me/projects", headers=get_auth_headers(admin))

    assert response.status_code == 200
    project_ids = {p["id"] for p in response.json()["items"]}
    assert shared.id in project_ids
    assert unshared.id not in project_ids


async def test_an_initiative_listing_still_answers_a_guild_admin_in_full(
    client: AsyncClient, session: AsyncSession
):
    """Naming one initiative asks about standing, and an admin's reaches it all.

    The companion to the test above: the same project the cross-initiative list
    withholds is returned the moment the admin asks for its initiative, which is
    what keeps this a change to navigation rather than to authority.
    """
    owner = await create_user(session, email="owner2@example.com")
    admin = await create_user(session, email="otheradmin2@example.com")

    guild = await create_guild(session, creator=owner, name="Shared Guild")
    await create_guild_membership(
        session, user=owner, guild=guild, role=GuildRole.admin
    )
    await create_guild_membership(
        session, user=admin, guild=guild, role=GuildRole.admin
    )

    elsewhere = await create_initiative(session, guild, owner, name="Not Theirs")
    unshared = await create_project(session, elsewhere, owner, name="Someone Else's")

    headers = get_auth_headers(admin)
    across = await client.get(f"/api/v1/c/{guild.id}/projects/", headers=headers)
    assert across.status_code == 200
    assert unshared.id not in {p["id"] for p in across.json()["items"]}

    within = await client.get(
        f"/api/v1/c/{guild.id}/projects/?initiative_id={elsewhere.id}",
        headers=headers,
    )
    assert within.status_code == 200
    assert unshared.id in {p["id"] for p in within.json()["items"]}


async def test_my_calendars_carry_a_guild_calendar(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """A guild calendar belongs to no initiative, and reaches every member.

    It is what makes this list unlike the other eight: the row answers to no
    initiative switch and to no initiative membership, and the guild member
    reading it here is in none of the guild's initiatives.
    """
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    calendar = await create_guild_calendar(session, a.guild, a.user)
    member = await acting_user(guild_role=GuildRole.member, guild=a.guild)

    response = await client.get("/api/v1/me/calendars", headers=member.headers)

    assert response.status_code == 200
    items = response.json()["items"]
    assert calendar.id in {c["id"] for c in items}
    assert next(c for c in items if c["id"] == calendar.id)["initiative_id"] is None


async def test_my_calendars_merge_across_guilds_and_apply_sharing(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Sharing is resolved per guild, as the guild is entered."""
    a = await acting_user(guild_role=GuildRole.member, initiative=True)
    await _enable_tools(client, a)
    shared = await create_calendar(session, a.initiative, a.user, name="Home Cal")
    secret = await create_calendar(session, a.initiative, a.user, name="Secret Cal")

    # Second guild the same user belongs to, with its own calendar.
    b = await acting_user(guild_role=GuildRole.member, initiative=True)
    await _enable_tools(client, b)
    await create_guild_membership(session, user=a.user, guild=b.guild)
    await create_initiative_member(session, b.initiative, a.user)
    away = await create_calendar(session, b.initiative, b.user, name="Away Cal")

    response = await client.get("/api/v1/me/calendars", headers=a.headers)
    assert response.status_code == 200
    names = {c["name"] for c in response.json()["items"]}
    assert {shared.name, secret.name, away.name} <= names

    member = await acting_user(
        guild_role=GuildRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )
    await strip_non_owner_grants(session, secret, a.user.id)
    member_resp = await client.get("/api/v1/me/calendars", headers=member.headers)
    assert member_resp.status_code == 200
    member_names = {c["name"] for c in member_resp.json()["items"]}
    assert shared.name in member_names
    assert secret.name not in member_names
    assert away.name not in member_names  # not a member of guild b


# ---------------------------------------------------------------------------
# The tab counts
# ---------------------------------------------------------------------------


async def test_my_tool_counts(client: AsyncClient, acting_user):
    """Every tool is answered for, with a zero where the caller has none."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _enable_tools(client, a)
    await _create(client, a, Tool.queue, "Standup")
    await _create(client, a, Tool.queue, "Retro")

    response = await client.get("/api/v1/me/tools/counts", headers=a.headers)

    assert response.status_code == 200
    counts = response.json()["counts"]
    assert counts["queue"] == 2
    # Present rather than absent: the page needs "none" to be distinguishable
    # from "not asked" when it decides which tabs to draw.
    assert counts["counter_group"] == 0
    # Derived from the enum rather than listed: every tool has a tab on this
    # page, so a new one belongs here the day it exists.
    assert set(counts) == {tool.value for tool in Tool}


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
    await _create(client, admin, Tool.queue, "Admin's Queue")

    everything = await client.get("/api/v1/me/tools/counts", headers=other.headers)
    assert everything.status_code == 200
    assert everything.json()["counts"]["queue"] == 1

    mine = await client.get(
        "/api/v1/me/tools/counts?created_by_me=true", headers=other.headers
    )
    assert mine.status_code == 200
    assert mine.json()["counts"]["queue"] == 0
