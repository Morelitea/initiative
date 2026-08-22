"""Endpoint tests for comments across every commentable surface, and for the
mention search (``/comments/mentions/search``)."""

import pytest
from httpx import AsyncClient
from sqlalchemy import delete as sa_delete
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.messages import CommentMessages
from app.core.tools import Tool
from app.models.platform.guild import GuildRole
from app.models.tenant.resource_grant import ResourceAccessLevel, ResourceGrant
from app.testing import (
    create_calendar,
    create_counter_group,
    create_dashboard,
    create_document,
    create_initiative_member,
    create_project,
    create_queue,
    create_task,
    create_user,
)
from app.testing.schema_harness import route_session_to_guild

# One factory per tool, uniform (session, initiative, creator) shape.
TOOL_FACTORIES = {
    Tool.project: create_project,
    Tool.document: create_document,
    Tool.queue: create_queue,
    Tool.counter_group: create_counter_group,
    Tool.calendar: create_calendar,
    Tool.dashboard: create_dashboard,
}


async def _tool_entity(session, tool: Tool, initiative, creator):
    """A tool entity whose only grant is the creator's owner grant, so each
    test states the sharing it needs explicitly (some factories seed an
    all-members read grant). Toggleable tools are switched on for the
    initiative first."""
    if not getattr(initiative, tool.view_permission, True):
        setattr(initiative, tool.view_permission, True)
        session.add(initiative)
        await session.commit()
    entity = await TOOL_FACTORIES[tool](session, initiative, creator)
    await route_session_to_guild(session, initiative.guild_id)
    await session.exec(
        sa_delete(ResourceGrant).where(
            ResourceGrant.resource_type == tool.value,
            ResourceGrant.resource_id == entity.id,
            ResourceGrant.level != ResourceAccessLevel.owner,
        )
    )
    await session.commit()
    return entity


async def _grant(session, tool: Tool, entity, user, level: ResourceAccessLevel):
    await route_session_to_guild(session, entity.guild_id)
    session.add(
        ResourceGrant(
            resource_type=tool.value,
            resource_id=entity.id,
            user_id=user.id,
            level=level,
            guild_id=entity.guild_id,
            initiative_id=entity.initiative_id,
        )
    )
    await session.commit()


def _param(tool: Tool) -> str:
    return f"{tool.value}_id"


@pytest.mark.integration
class TestToolComments:
    """The comment surface every tool carries: posting takes write access on
    the entity, reading its thread takes read access — the same DAC decision
    the entity's own endpoints make."""

    @pytest.mark.parametrize("tool", list(Tool))
    async def test_creator_posts_and_lists(self, client, session, acting_user, tool):
        a = await acting_user(guild_role=GuildRole.member, initiative=True)
        entity = await _tool_entity(session, tool, a.initiative, a.user)

        created = await client.post(
            a.g("/comments/"),
            headers=a.headers,
            json={"content": "First!", _param(tool): entity.id},
        )
        assert created.status_code == 201, created.text
        body = created.json()
        assert body[_param(tool)] == entity.id
        if tool is Tool.project:
            assert body["project_id"] == entity.id

        listed = await client.get(
            a.g("/comments/"), headers=a.headers, params={_param(tool): entity.id}
        )
        assert listed.status_code == 200, listed.text
        assert [c["id"] for c in listed.json()] == [body["id"]]

    @pytest.mark.parametrize("tool", list(Tool))
    async def test_member_without_grant_is_denied(
        self, client, session, acting_user, tool
    ):
        a = await acting_user(guild_role=GuildRole.member, initiative=True)
        entity = await _tool_entity(session, tool, a.initiative, a.user)
        b = await acting_user(
            guild_role=GuildRole.member,
            guild=a.guild,
            initiative=a.initiative,
            initiative_role="member",
        )

        listed = await client.get(
            a.g("/comments/"), headers=b.headers, params={_param(tool): entity.id}
        )
        assert listed.status_code == 403
        assert listed.json()["detail"] == CommentMessages.PERMISSION_DENIED

        posted = await client.post(
            a.g("/comments/"),
            headers=b.headers,
            json={"content": "Hi", _param(tool): entity.id},
        )
        assert posted.status_code == 403

    @pytest.mark.parametrize("tool", list(Tool))
    async def test_any_grant_level_joins_the_discussion(
        self, client, session, acting_user, tool
    ):
        # The rule tasks and documents have always had: any grant level on the
        # parent (read included) lets a member read AND post to its thread.
        a = await acting_user(guild_role=GuildRole.member, initiative=True)
        entity = await _tool_entity(session, tool, a.initiative, a.user)
        b = await acting_user(
            guild_role=GuildRole.member,
            guild=a.guild,
            initiative=a.initiative,
            initiative_role="member",
        )
        await _grant(session, tool, entity, b.user, ResourceAccessLevel.read)

        listed = await client.get(
            a.g("/comments/"), headers=b.headers, params={_param(tool): entity.id}
        )
        assert listed.status_code == 200

        posted = await client.post(
            a.g("/comments/"),
            headers=b.headers,
            json={"content": "Hi", _param(tool): entity.id},
        )
        assert posted.status_code == 201, posted.text

    @pytest.mark.parametrize("tool", list(Tool))
    async def test_guild_admin_reaches_every_thread(
        self, client, session, acting_user, tool
    ):
        a = await acting_user(guild_role=GuildRole.member, initiative=True)
        entity = await _tool_entity(session, tool, a.initiative, a.user)
        admin = await acting_user(guild_role=GuildRole.admin, guild=a.guild)

        listed = await client.get(
            a.g("/comments/"), headers=admin.headers, params={_param(tool): entity.id}
        )
        assert listed.status_code == 200

        posted = await client.post(
            a.g("/comments/"),
            headers=admin.headers,
            json={"content": "Hello", _param(tool): entity.id},
        )
        assert posted.status_code == 201, posted.text

    @pytest.mark.parametrize("tool", list(Tool))
    async def test_a_non_member_finds_nothing(self, client, session, acting_user, tool):
        a = await acting_user(guild_role=GuildRole.member, initiative=True)
        entity = await _tool_entity(session, tool, a.initiative, a.user)
        outsider = await acting_user(guild_role=GuildRole.member, guild=a.guild)

        listed = await client.get(
            a.g("/comments/"),
            headers=outsider.headers,
            params={_param(tool): entity.id},
        )
        assert listed.status_code == 404

    @pytest.mark.parametrize(
        "tool", [t for t in Tool if t not in (Tool.project, Tool.document)]
    )
    async def test_a_disabled_tool_takes_no_comments(
        self, client, session, acting_user, tool
    ):
        a = await acting_user(guild_role=GuildRole.member, initiative=True)
        entity = await _tool_entity(session, tool, a.initiative, a.user)
        setattr(a.initiative, tool.view_permission, False)
        session.add(a.initiative)
        await session.commit()

        listed = await client.get(
            a.g("/comments/"), headers=a.headers, params={_param(tool): entity.id}
        )
        assert listed.status_code == 403

    async def test_a_reply_must_share_the_parent(self, client, session, acting_user):
        a = await acting_user(guild_role=GuildRole.member, initiative=True)
        queue = await _tool_entity(session, Tool.queue, a.initiative, a.user)
        other = await _tool_entity(session, Tool.queue, a.initiative, a.user)

        root = await client.post(
            a.g("/comments/"),
            headers=a.headers,
            json={"content": "Root", "queue_id": queue.id},
        )
        assert root.status_code == 201

        mismatch = await client.post(
            a.g("/comments/"),
            headers=a.headers,
            json={
                "content": "Reply",
                "queue_id": other.id,
                "parent_comment_id": root.json()["id"],
            },
        )
        assert mismatch.status_code == 400
        assert mismatch.json()["detail"] == CommentMessages.PARENT_MISMATCH

        reply = await client.post(
            a.g("/comments/"),
            headers=a.headers,
            json={
                "content": "Reply",
                "queue_id": queue.id,
                "parent_comment_id": root.json()["id"],
            },
        )
        assert reply.status_code == 201

    async def test_exactly_one_target(self, client, session, acting_user):
        a = await acting_user(guild_role=GuildRole.member, initiative=True)
        project = await _tool_entity(session, Tool.project, a.initiative, a.user)
        queue = await _tool_entity(session, Tool.queue, a.initiative, a.user)

        two = await client.post(
            a.g("/comments/"),
            headers=a.headers,
            json={"content": "Hi", "project_id": project.id, "queue_id": queue.id},
        )
        assert two.status_code == 422

        none = await client.post(
            a.g("/comments/"), headers=a.headers, json={"content": "Hi"}
        )
        assert none.status_code == 422

    async def test_a_task_comment_reports_its_project(
        self, client, session, acting_user
    ):
        a = await acting_user(
            guild_role=GuildRole.member, initiative=True, project=True
        )
        task = await create_task(session, a.project)

        created = await client.post(
            a.g("/comments/"),
            headers=a.headers,
            json={"content": "On the task", "task_id": task.id},
        )
        assert created.status_code == 201, created.text
        body = created.json()
        assert body["task_id"] == task.id
        assert body["project_id"] == a.project.id

    async def test_recent_carries_tool_comments(self, client, session, acting_user):
        a = await acting_user(
            guild_role=GuildRole.member, initiative=True, project=True
        )
        queue = await _tool_entity(session, Tool.queue, a.initiative, a.user)
        task = await create_task(session, a.project)

        for payload in (
            {"content": "On the queue", "queue_id": queue.id},
            {"content": "On the task", "task_id": task.id},
        ):
            posted = await client.post(
                a.g("/comments/"), headers=a.headers, json=payload
            )
            assert posted.status_code == 201, posted.text

        recent = await client.get(a.g("/comments/recent"), headers=a.headers)
        assert recent.status_code == 200, recent.text
        by_type = {e["entity_type"]: e for e in recent.json()}
        assert by_type["queue"]["entity_id"] == queue.id
        assert by_type["queue"]["entity_name"] == queue.name
        assert by_type["queue"]["initiative_id"] == a.initiative.id
        assert by_type["task"]["entity_id"] == task.id
        assert by_type["task"]["project_id"] == a.project.id


@pytest.mark.integration
async def test_mention_search_users_paginated_with_avatars(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """User mention search returns the paginated envelope; each user item
    carries an avatar so the picker can render a face."""
    admin = await acting_user(guild_role=GuildRole.admin, initiative=True)
    for name in ("Alice Ant", "Bob Bee", "Cara Cat"):
        member = await create_user(session, full_name=name, avatar_base64="data:x")
        await create_initiative_member(session, admin.initiative, member)

    response = await client.get(
        admin.g("/comments/mentions/search"),
        headers=admin.headers,
        params={
            "entity_type": "user",
            "initiative_id": admin.initiative.id,
            "page_size": 2,
        },
    )

    assert response.status_code == 200
    body = response.json()
    # Envelope shape mirrors the member search endpoints.
    assert set(body.keys()) == {
        "items",
        "total_count",
        "page",
        "page_size",
        "has_next",
        "has_prev",
    }
    assert body["page_size"] == 2
    assert len(body["items"]) == 2
    assert body["total_count"] >= 3  # 3 added members (+ maybe the admin)
    assert body["has_next"] is True
    item = body["items"][0]
    assert item["type"] == "user"
    assert "avatar_base64" in item and "avatar_url" in item


@pytest.mark.integration
async def test_mention_search_users_filters_by_name(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The `q` param filters user suggestions by name (case-insensitive)."""
    admin = await acting_user(guild_role=GuildRole.admin, initiative=True)
    for name in ("Alice Ant", "Bob Bee"):
        member = await create_user(session, full_name=name)
        await create_initiative_member(session, admin.initiative, member)

    response = await client.get(
        admin.g("/comments/mentions/search"),
        headers=admin.headers,
        params={
            "entity_type": "user",
            "initiative_id": admin.initiative.id,
            "q": "alice",
        },
    )

    assert response.status_code == 200
    body = response.json()
    names = {item["display_text"] for item in body["items"]}
    assert "Alice Ant" in names
    assert "Bob Bee" not in names


@pytest.mark.integration
async def test_mention_search_unknown_initiative_404(
    client: AsyncClient, session: AsyncSession, acting_user
):
    admin = await acting_user(guild_role=GuildRole.admin, initiative=True)
    response = await client.get(
        admin.g("/comments/mentions/search"),
        headers=admin.headers,
        params={"entity_type": "user", "initiative_id": 999999},
    )
    assert response.status_code == 404


async def test_a_trashed_resource_reads_back_for_its_deleted_event(
    client, session, acting_user
):
    """A ``deleted`` event is unactionable unless its id still resolves.

    The row survives in the trash until retention, so a read-back may ask for
    it — access checked exactly as for a live one. That is what makes the
    ``deleted`` half of the bus actionable: the id still resolves.
    """
    from datetime import datetime, timezone

    from app.models.platform.guild import GuildRole
    from app.testing import create_task

    a = await acting_user(guild_role=GuildRole.admin, initiative=True, project=True)
    task = await create_task(session, a.project)
    task_id = task.id

    task.deleted_at = datetime.now(timezone.utc)
    session.add(task)
    await session.commit()

    gone = await client.get(a.g(f"/tasks/{task_id}"), headers=a.headers)
    assert gone.status_code == 404, "a trashed task should be hidden by default"

    found = await client.get(
        a.g(f"/tasks/{task_id}"), params={"include_deleted": "true"}, headers=a.headers
    )
    assert found.status_code == 200, found.text
    assert found.json()["id"] == task_id
    # The event already said it was deleted; what the read-back supplies is the
    # content to act on. Read payloads do not carry deleted_at today.


@pytest.mark.integration
async def test_guild_calendar_comments_reach_every_member(client, session, acting_user):
    """A guild calendar names no initiative; its everyone-grant reads as the
    whole guild, so any member can join its thread — same rule, wider room."""
    from app.testing import create_guild_calendar

    admin = await acting_user(guild_role=GuildRole.admin)
    calendar = await create_guild_calendar(session, admin.guild, admin.user)
    member = await acting_user(guild_role=GuildRole.member, guild=admin.guild)

    posted = await client.post(
        admin.g("/comments/"),
        headers=member.headers,
        json={"content": "Game night?", "calendar_id": calendar.id},
    )
    assert posted.status_code == 201, posted.text

    listed = await client.get(
        admin.g("/comments/"),
        headers=member.headers,
        params={"calendar_id": calendar.id},
    )
    assert listed.status_code == 200
    assert [c["content"] for c in listed.json()] == ["Game night?"]


@pytest.mark.integration
async def test_recent_drops_comments_of_a_disabled_tool(client, session, acting_user):
    """Switching a tool off takes its threads out of the recent feed, exactly
    as it takes the threads themselves away."""
    a = await acting_user(guild_role=GuildRole.member, initiative=True)
    queue = await _tool_entity(session, Tool.queue, a.initiative, a.user)

    posted = await client.post(
        a.g("/comments/"),
        headers=a.headers,
        json={"content": "Queue talk", "queue_id": queue.id},
    )
    assert posted.status_code == 201, posted.text

    recent = await client.get(a.g("/comments/recent"), headers=a.headers)
    assert any(e["entity_type"] == "queue" for e in recent.json())

    setattr(a.initiative, Tool.queue.view_permission, False)
    session.add(a.initiative)
    await session.commit()

    recent = await client.get(a.g("/comments/recent"), headers=a.headers)
    assert recent.status_code == 200
    assert not any(e["entity_type"] == "queue" for e in recent.json())
