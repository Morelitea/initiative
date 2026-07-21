"""Behavioral tests for tag assignment — the shared service path, the bulk
endpoint, soft-delete interaction, and the cross-initiative isolation gate.
"""

import pytest
from httpx import AsyncClient
from sqlmodel import select

from app.models.platform.guild import GuildRole
from app.models.tenant.tag import TaskTag
from app.testing import (
    create_counter_group,
    create_initiative,
    create_queue,
    create_tag,
    create_task,
)


async def _task_tag_ids(session, guild_id: int, task_id: int) -> set[int]:
    from app.db.session import clear_rls_context
    from app.testing.schema_harness import route_session_to_guild

    clear_rls_context(session)
    await route_session_to_guild(session, guild_id)
    result = await session.exec(
        select(TaskTag.tag_id).where(TaskTag.task_id == task_id)
    )
    return set(result.all())


# ---------------------------------------------------------------------------
# Tag dictionary permissions (deliberate product decision)
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_any_guild_member_can_manage_the_tag_dictionary(
    client: AsyncClient, acting_user
):
    """Product decision: the tag dictionary is a guild-wide folksonomy.

    EVERY guild member — even one in no initiative — can create, rename,
    recolor, and trash tags; only hard purge is admin-gated (the RESTRICTIVE
    RLS policy). This test pins the decision so the openness reads as
    intentional, not as a missing gate.
    """
    admin = await acting_user(guild_role=GuildRole.admin)
    member = await acting_user(guild_role=GuildRole.member, guild=admin.guild)

    created = await client.post(
        member.g("/tags/"),
        headers=member.headers,
        json={"name": "Folk Tag", "color": "#112233"},
    )
    assert created.status_code == 201
    tag_id = created.json()["id"]

    renamed = await client.patch(
        member.g(f"/tags/{tag_id}"),
        headers=member.headers,
        json={"name": "Folk Tag Renamed", "color": "#445566"},
    )
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "Folk Tag Renamed"

    trashed = await client.delete(member.g(f"/tags/{tag_id}"), headers=member.headers)
    assert trashed.status_code == 204


# ---------------------------------------------------------------------------
# Single-entity set-tags (shared service path)
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_set_task_tags_replaces_and_dedups(
    client: AsyncClient, acting_user, session
):
    a = await acting_user(guild_role=GuildRole.admin, initiative=True, project=True)
    tag = await create_tag(session, a.guild)
    other = await create_tag(session, a.guild)
    task = await create_task(session, a.project)

    response = await client.put(
        a.g(f"/tasks/{task.id}/tags"),
        headers=a.headers,
        json={"tag_ids": [tag.id, other.id, tag.id]},
    )
    assert response.status_code == 200
    assert {t["id"] for t in response.json()["tags"]} == {tag.id, other.id}

    response = await client.put(
        a.g(f"/tasks/{task.id}/tags"), headers=a.headers, json={"tag_ids": [other.id]}
    )
    assert response.status_code == 200
    assert await _task_tag_ids(session, a.guild.id, task.id) == {other.id}


@pytest.mark.integration
async def test_set_tags_rejects_trashed_tag(client: AsyncClient, acting_user, session):
    """A trashed tag id is invalid everywhere — the incident regression: a
    stale client merging a since-trashed tag id must get a clean 400."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True, project=True)
    tag = await create_tag(session, a.guild)
    task = await create_task(session, a.project)

    delete = await client.delete(a.g(f"/tags/{tag.id}"), headers=a.headers)
    assert delete.status_code == 204

    response = await client.put(
        a.g(f"/tasks/{task.id}/tags"), headers=a.headers, json={"tag_ids": [tag.id]}
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "INVALID_TAG_IDS"


@pytest.mark.integration
async def test_set_tags_rejects_other_guilds_tag(
    client: AsyncClient, acting_user, session
):
    a = await acting_user(guild_role=GuildRole.admin, initiative=True, project=True)
    b = await acting_user(guild_role=GuildRole.admin, initiative=True)
    foreign_tag = await create_tag(session, b.guild)
    task = await create_task(session, a.project)

    response = await client.put(
        a.g(f"/tasks/{task.id}/tags"),
        headers=a.headers,
        json={"tag_ids": [foreign_tag.id]},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "INVALID_TAG_IDS"


@pytest.mark.integration
async def test_generic_tool_tags_route_covers_every_tool(
    client: AsyncClient, acting_user, session
):
    """PUT /tools/{tool}/{tool_id}/tags works for EVERY Tool member. The
    entity map below must span the enum, so a new tool fails here until the
    generic route demonstrably covers it too."""
    from app.core.tools import Tool
    from app.models.tenant.advanced_tool import AdvancedTool
    from app.models.tenant.initiative import Initiative
    from app.testing import (
        create_calendar_event,
        create_document,
        create_project,
        route_session_to_guild,
    )

    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    # The initiative factory enables queues + counter groups; flip on the
    # remaining toggleable tools so the feature gate passes for all of them.
    await route_session_to_guild(session, a.guild.id)
    initiative = await session.get(Initiative, a.initiative.id)
    initiative.calendar_events_enabled = True
    initiative.advanced_tools_enabled = True
    session.add(initiative)
    advanced = AdvancedTool(
        guild_id=a.guild.id,
        initiative_id=a.initiative.id,
        name="Adv",
        created_by_id=a.user.id,
    )
    session.add(advanced)
    await session.commit()
    tag = await create_tag(session, a.guild)

    entities = {
        Tool.project: await create_project(session, a.initiative, a.user),
        Tool.document: await create_document(session, a.initiative, a.user),
        Tool.queue: await create_queue(session, a.initiative, a.user),
        Tool.counter_group: await create_counter_group(session, a.initiative, a.user),
        Tool.calendar_event: await create_calendar_event(session, a.initiative, a.user),
        Tool.advanced_tool: advanced,
    }
    assert set(entities) == set(Tool)

    for tool, entity in entities.items():
        response = await client.put(
            a.g(f"/tools/{tool.value}/{entity.id}/tags"),
            headers=a.headers,
            json={"tag_ids": [tag.id]},
        )
        assert response.status_code == 200, (tool, response.text)
        assert [t["id"] for t in response.json()] == [tag.id], tool

    # The assignment is served back through the tool's own read path.
    listing = await client.get(a.g("/queues/"), headers=a.headers)
    assert listing.status_code == 200
    (queue_row,) = [
        q for q in listing.json()["items"] if q["id"] == entities[Tool.queue].id
    ]
    assert [t["id"] for t in queue_row["tags"]] == [tag.id]


@pytest.mark.integration
async def test_generic_tool_tags_route_rejects_unknown_tool(
    client: AsyncClient, acting_user
):
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    response = await client.put(
        a.g("/tools/task/1/tags"), headers=a.headers, json={"tag_ids": []}
    )
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Bulk edit
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_bulk_add_and_remove_task_tags(client: AsyncClient, acting_user, session):
    a = await acting_user(guild_role=GuildRole.admin, initiative=True, project=True)
    keep = await create_tag(session, a.guild)
    added = await create_tag(session, a.guild)
    tasks = [await create_task(session, a.project) for _ in range(3)]
    first = tasks[0]

    seed = await client.put(
        a.g(f"/tasks/{first.id}/tags"), headers=a.headers, json={"tag_ids": [keep.id]}
    )
    assert seed.status_code == 200

    response = await client.post(
        a.g("/tags/bulk"),
        headers=a.headers,
        json={
            "target_type": "task",
            "target_ids": [t.id for t in tasks],
            "add_tag_ids": [added.id],
        },
    )
    assert response.status_code == 200
    assert response.json()["updated_count"] == 3
    # Adds are idempotent and preserve unrelated existing tags.
    assert await _task_tag_ids(session, a.guild.id, first.id) == {keep.id, added.id}
    for task in tasks[1:]:
        assert await _task_tag_ids(session, a.guild.id, task.id) == {added.id}

    response = await client.post(
        a.g("/tags/bulk"),
        headers=a.headers,
        json={
            "target_type": "task",
            "target_ids": [t.id for t in tasks],
            "remove_tag_ids": [added.id],
        },
    )
    assert response.status_code == 200
    assert await _task_tag_ids(session, a.guild.id, first.id) == {keep.id}
    for task in tasks[1:]:
        assert await _task_tag_ids(session, a.guild.id, task.id) == set()


@pytest.mark.integration
async def test_bulk_edit_requires_an_operation(client: AsyncClient, acting_user):
    a = await acting_user(guild_role=GuildRole.admin, initiative=True, project=True)
    response = await client.post(
        a.g("/tags/bulk"),
        headers=a.headers,
        json={"target_type": "task", "target_ids": [1]},
    )
    assert response.status_code == 422


@pytest.mark.integration
async def test_bulk_edit_rejects_trashed_tag_atomically(
    client: AsyncClient, acting_user, session
):
    a = await acting_user(guild_role=GuildRole.admin, initiative=True, project=True)
    trashed = await create_tag(session, a.guild)
    task = await create_task(session, a.project)
    delete = await client.delete(a.g(f"/tags/{trashed.id}"), headers=a.headers)
    assert delete.status_code == 204

    response = await client.post(
        a.g("/tags/bulk"),
        headers=a.headers,
        json={
            "target_type": "task",
            "target_ids": [task.id],
            "add_tag_ids": [trashed.id],
        },
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "INVALID_TAG_IDS"
    assert await _task_tag_ids(session, a.guild.id, task.id) == set()


@pytest.mark.integration
async def test_bulk_edit_denied_without_project_write(
    client: AsyncClient, acting_user, session
):
    """A member without write on the tasks' project can bulk-edit nothing —
    the whole request fails and no junction row changes."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True, project=True)
    tag = await create_tag(session, a.guild)
    task = await create_task(session, a.project)
    b = await acting_user(
        guild_role=GuildRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )

    response = await client.post(
        b.g("/tags/bulk"),
        headers=b.headers,
        json={
            "target_type": "task",
            "target_ids": [task.id],
            "add_tag_ids": [tag.id],
        },
    )
    assert response.status_code in (403, 404)
    assert await _task_tag_ids(session, a.guild.id, task.id) == set()


# ---------------------------------------------------------------------------
# Initiative isolation (gate 2)
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_cross_initiative_member_cannot_touch_tags(
    client: AsyncClient, acting_user, session
):
    """A member of a different initiative in the same guild gets 404 (RLS
    hides the row) for both the per-entity and bulk tag paths."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True, project=True)
    tag = await create_tag(session, a.guild)
    task = await create_task(session, a.project)

    # b belongs to the same guild but a DIFFERENT initiative (creator → PM
    # there), so a's task must be invisible to them.
    b = await acting_user(guild_role=GuildRole.member, guild=a.guild)
    await create_initiative(session, a.guild, b.user)

    response = await client.put(
        b.g(f"/tasks/{task.id}/tags"), headers=b.headers, json={"tag_ids": [tag.id]}
    )
    assert response.status_code == 404

    # Same gate on the generic tool route: a's project is invisible to b.
    response = await client.put(
        b.g(f"/tools/project/{a.project.id}/tags"),
        headers=b.headers,
        json={"tag_ids": [tag.id]},
    )
    assert response.status_code == 404

    response = await client.post(
        b.g("/tags/bulk"),
        headers=b.headers,
        json={
            "target_type": "task",
            "target_ids": [task.id],
            "add_tag_ids": [tag.id],
        },
    )
    assert response.status_code == 404
    assert await _task_tag_ids(session, a.guild.id, task.id) == set()
