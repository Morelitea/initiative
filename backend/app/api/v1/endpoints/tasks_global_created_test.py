"""
Integration tests for the global_created task scope.

Tests the GET /api/v1/tasks/?scope=global_created endpoint which returns
tasks created by the current user across all guilds they belong to.
"""

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.guild import GuildRole
from app.models.task import Task, TaskPriority
from app.testing.factories import (
    create_guild,
    create_guild_membership,
    create_initiative,
    create_project,
    create_user,
    get_guild_headers,
)


async def _create_task(session, project, title="Test Task", *, created_by_id=None):
    """Helper to create a task with optional created_by_id."""
    from app.services import task_statuses as task_statuses_service

    await task_statuses_service.ensure_default_statuses(session, project.id)
    status = await task_statuses_service.get_default_status(session, project.id)

    task = Task(
        title=title,
        project_id=project.id,
        task_status_id=status.id,
        guild_id=project.guild_id,
        created_by_id=created_by_id,
    )
    session.add(task)
    await session.commit()
    await session.refresh(task)
    return task


async def _setup_guild_with_project(session, user, *, guild_name="Test Guild"):
    """Create a guild, membership, initiative, and project for the user."""
    guild = await create_guild(session, creator=user, name=guild_name)
    await create_guild_membership(
        session, user=user, guild=guild, role=GuildRole.admin
    )
    initiative = await create_initiative(session, guild, user, name="Initiative")
    project = await create_project(session, initiative, user, name="Project")
    return guild, initiative, project


@pytest.mark.integration
async def test_create_task_sets_created_by_id(
    client: AsyncClient, session: AsyncSession
):
    """Creating a task via the API should populate created_by_id."""
    user = await create_user(session, email="creator@example.com")
    guild, initiative, project = await _setup_guild_with_project(session, user)

    from app.services import task_statuses as task_statuses_service

    await task_statuses_service.ensure_default_statuses(session, project.id)
    status = await task_statuses_service.get_default_status(session, project.id)

    headers = get_guild_headers(guild, user)
    payload = {
        "title": "Created via API",
        "project_id": project.id,
        "task_status_id": status.id,
    }
    response = await client.post("/api/v1/tasks/", headers=headers, json=payload)

    assert response.status_code == 201
    data = response.json()
    assert data["created_by_id"] == user.id


@pytest.mark.integration
async def test_list_global_created_tasks(
    client: AsyncClient, session: AsyncSession
):
    """scope=global_created should return tasks created by the current user."""
    creator = await create_user(session, email="creator@example.com")
    guild, _, project = await _setup_guild_with_project(session, creator)

    task1 = await _create_task(
        session, project, "My Task 1", created_by_id=creator.id
    )
    task2 = await _create_task(
        session, project, "My Task 2", created_by_id=creator.id
    )

    headers = get_guild_headers(guild, creator)
    response = await client.get(
        "/api/v1/tasks/?scope=global_created", headers=headers
    )

    assert response.status_code == 200
    data = response.json()
    task_ids = {t["id"] for t in data["items"]}
    assert task1.id in task_ids
    assert task2.id in task_ids
    assert data["total_count"] >= 2


@pytest.mark.integration
async def test_list_global_created_tasks_excludes_others(
    client: AsyncClient, session: AsyncSession
):
    """scope=global_created should NOT return tasks created by other users."""
    creator = await create_user(session, email="creator@example.com")
    other = await create_user(session, email="other@example.com")
    guild, _, project = await _setup_guild_with_project(session, creator)
    await create_guild_membership(session, user=other, guild=guild)

    my_task = await _create_task(
        session, project, "My Task", created_by_id=creator.id
    )
    other_task = await _create_task(
        session, project, "Other Task", created_by_id=other.id
    )

    headers = get_guild_headers(guild, creator)
    response = await client.get(
        "/api/v1/tasks/?scope=global_created", headers=headers
    )

    assert response.status_code == 200
    task_ids = {t["id"] for t in response.json()["items"]}
    assert my_task.id in task_ids
    assert other_task.id not in task_ids


@pytest.mark.integration
async def test_list_global_created_tasks_excludes_null_created_by(
    client: AsyncClient, session: AsyncSession
):
    """Tasks with no created_by_id (legacy) should not appear in global_created."""
    user = await create_user(session, email="user@example.com")
    guild, _, project = await _setup_guild_with_project(session, user)

    # Task without created_by_id (simulates pre-migration task)
    legacy_task = await _create_task(session, project, "Legacy Task")
    my_task = await _create_task(
        session, project, "My Task", created_by_id=user.id
    )

    headers = get_guild_headers(guild, user)
    response = await client.get(
        "/api/v1/tasks/?scope=global_created", headers=headers
    )

    assert response.status_code == 200
    task_ids = {t["id"] for t in response.json()["items"]}
    assert my_task.id in task_ids
    assert legacy_task.id not in task_ids


@pytest.mark.integration
async def test_list_global_created_tasks_priority_filter(
    client: AsyncClient, session: AsyncSession
):
    """scope=global_created should respect priority filters."""
    user = await create_user(session, email="user@example.com")
    guild, _, project = await _setup_guild_with_project(session, user)

    high_task = await _create_task(
        session, project, "High Priority", created_by_id=user.id
    )
    high_task.priority = TaskPriority.high
    session.add(high_task)

    low_task = await _create_task(
        session, project, "Low Priority", created_by_id=user.id
    )
    low_task.priority = TaskPriority.low
    session.add(low_task)
    await session.commit()

    headers = get_guild_headers(guild, user)
    response = await client.get(
        "/api/v1/tasks/?scope=global_created&priorities=high", headers=headers
    )

    assert response.status_code == 200
    task_ids = {t["id"] for t in response.json()["items"]}
    assert high_task.id in task_ids
    assert low_task.id not in task_ids


@pytest.mark.integration
async def test_list_global_created_tasks_guild_filter(
    client: AsyncClient, session: AsyncSession
):
    """scope=global_created with guild_ids filter should only return matching guilds."""
    user = await create_user(session, email="user@example.com")
    guild1, _, project1 = await _setup_guild_with_project(
        session, user, guild_name="Guild 1"
    )
    guild2, _, project2 = await _setup_guild_with_project(
        session, user, guild_name="Guild 2"
    )

    task1 = await _create_task(
        session, project1, "Guild 1 Task", created_by_id=user.id
    )
    task2 = await _create_task(
        session, project2, "Guild 2 Task", created_by_id=user.id
    )

    # Filter to guild1 only
    headers = get_guild_headers(guild1, user)
    response = await client.get(
        f"/api/v1/tasks/?scope=global_created&guild_ids={guild1.id}",
        headers=headers,
    )

    assert response.status_code == 200
    task_ids = {t["id"] for t in response.json()["items"]}
    assert task1.id in task_ids
    assert task2.id not in task_ids


@pytest.mark.integration
async def test_list_global_created_tasks_pagination(
    client: AsyncClient, session: AsyncSession
):
    """scope=global_created should support pagination."""
    user = await create_user(session, email="user@example.com")
    guild, _, project = await _setup_guild_with_project(session, user)

    # Create 3 tasks
    for i in range(3):
        await _create_task(
            session, project, f"Task {i}", created_by_id=user.id
        )

    headers = get_guild_headers(guild, user)

    # Page 1 with page_size=2
    response = await client.get(
        "/api/v1/tasks/?scope=global_created&page=1&page_size=2", headers=headers
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data["items"]) == 2
    assert data["total_count"] == 3
    assert data["has_next"] is True

    # Page 2
    response = await client.get(
        "/api/v1/tasks/?scope=global_created&page=2&page_size=2", headers=headers
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data["items"]) == 1
    assert data["has_next"] is False
