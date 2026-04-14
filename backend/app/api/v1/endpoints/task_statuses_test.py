"""
Integration tests for task status endpoints.

Covers the color/icon fields added for customizable status appearance,
including category-driven defaults and PATCH behavior around category changes.
"""

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.task import TaskStatusCategory
from app.services import task_statuses as task_statuses_service
from app.testing.factories import (
    create_guild,
    create_guild_membership,
    create_initiative,
    create_project,
    create_user,
    get_guild_headers,
)


async def _setup_project(session: AsyncSession):
    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    await create_guild_membership(session, user=user, guild=guild)
    initiative = await create_initiative(session, guild, user, name="Test Initiative")
    project = await create_project(session, initiative, user, name="Test Project")
    headers = get_guild_headers(guild, user)
    return project, headers


@pytest.mark.integration
async def test_create_status_uses_category_defaults(
    client: AsyncClient, session: AsyncSession
):
    project, headers = await _setup_project(session)

    response = await client.post(
        f"/api/v1/projects/{project.id}/task-statuses/",
        json={"name": "Review", "category": "todo"},
        headers=headers,
    )

    assert response.status_code == 201
    body = response.json()
    assert body["color"] == "#FBBF24"
    assert body["icon"] == "circle-pause"


@pytest.mark.integration
async def test_create_status_respects_explicit_color_icon(
    client: AsyncClient, session: AsyncSession
):
    project, headers = await _setup_project(session)

    response = await client.post(
        f"/api/v1/projects/{project.id}/task-statuses/",
        json={
            "name": "Shipping",
            "category": "in_progress",
            "color": "#FF00AA",
            "icon": "rocket",
        },
        headers=headers,
    )

    assert response.status_code == 201
    body = response.json()
    assert body["color"] == "#FF00AA"
    assert body["icon"] == "rocket"


@pytest.mark.integration
async def test_patch_updates_color_and_icon(
    client: AsyncClient, session: AsyncSession
):
    project, headers = await _setup_project(session)
    statuses = await task_statuses_service.ensure_default_statuses(session, project.id)
    await session.commit()
    backlog = next(s for s in statuses if s.category == TaskStatusCategory.backlog)

    response = await client.patch(
        f"/api/v1/projects/{project.id}/task-statuses/{backlog.id}",
        json={"color": "#123456", "icon": "star"},
        headers=headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["color"] == "#123456"
    assert body["icon"] == "star"


@pytest.mark.integration
async def test_patch_category_change_keeps_existing_color_icon(
    client: AsyncClient, session: AsyncSession
):
    project, headers = await _setup_project(session)
    statuses = await task_statuses_service.ensure_default_statuses(session, project.id)
    await session.commit()
    # Pick the "Blocked" (category=todo) status so changing category away from
    # todo is allowed (backlog and done cannot be moved to a different category
    # when they're the last of their kind, but todo has no such restriction).
    blocked = next(
        s
        for s in statuses
        if s.category == TaskStatusCategory.todo and s.name == "Blocked"
    )

    # First set explicit custom color/icon
    first = await client.patch(
        f"/api/v1/projects/{project.id}/task-statuses/{blocked.id}",
        json={"color": "#ABCDEF", "icon": "flag"},
        headers=headers,
    )
    assert first.status_code == 200

    # Now change category only — color/icon should remain untouched
    second = await client.patch(
        f"/api/v1/projects/{project.id}/task-statuses/{blocked.id}",
        json={"category": "in_progress"},
        headers=headers,
    )
    assert second.status_code == 200
    body = second.json()
    assert body["category"] == "in_progress"
    assert body["color"] == "#ABCDEF"
    assert body["icon"] == "flag"


@pytest.mark.integration
async def test_create_status_rejects_invalid_hex_color(
    client: AsyncClient, session: AsyncSession
):
    project, headers = await _setup_project(session)

    response = await client.post(
        f"/api/v1/projects/{project.id}/task-statuses/",
        json={
            "name": "Bad color",
            "category": "todo",
            "color": "notcolor",
        },
        headers=headers,
    )

    assert response.status_code == 422


@pytest.mark.integration
async def test_default_seeded_statuses_have_category_colors(
    session: AsyncSession,
):
    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    await create_guild_membership(session, user=user, guild=guild)
    initiative = await create_initiative(session, guild, user, name="Seed Initiative")
    project = await create_project(session, initiative, user, name="Seed Project")

    statuses = await task_statuses_service.ensure_default_statuses(session, project.id)
    by_category = {s.category: s for s in statuses}

    assert by_category[TaskStatusCategory.backlog].color == "#94A3B8"
    assert by_category[TaskStatusCategory.backlog].icon == "circle-dashed"
    assert by_category[TaskStatusCategory.in_progress].color == "#60A5FA"
    assert by_category[TaskStatusCategory.in_progress].icon == "circle-play"
    assert by_category[TaskStatusCategory.todo].color == "#FBBF24"
    assert by_category[TaskStatusCategory.todo].icon == "circle-pause"
    assert by_category[TaskStatusCategory.done].color == "#34D399"
    assert by_category[TaskStatusCategory.done].icon == "circle-check"
