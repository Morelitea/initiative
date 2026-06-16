"""
Integration tests for the assigned-tasks /me view.

Tests GET /api/v1/me/tasks, which returns tasks ASSIGNED to the current user
across all guilds they belong to (distinct from /me/tasks/created, which keys
off created_by_id).
"""

import json

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.guild import GuildRole
from app.models.task import Task, TaskAssignee, TaskPriority
from app.testing.factories import (
    create_guild,
    create_guild_membership,
    create_initiative,
    create_project,
    create_user,
    get_guild_headers,
)


async def _create_task(
    session,
    project,
    title="Test Task",
    *,
    created_by_id=None,
    due_date=None,
    start_date=None,
    priority=TaskPriority.medium,
):
    """Create a task in ``project``'s guild schema."""
    from app.db.session import set_rls_context
    from app.services import task_statuses as task_statuses_service

    # Route status setup + the task into the project's guild schema; a prior
    # setup may have left the search_path on a different guild.
    await set_rls_context(session, user_id=created_by_id, guild_id=project.guild_id)
    await task_statuses_service.ensure_default_statuses(session, project.id)
    status = await task_statuses_service.get_default_status(session, project.id)

    task = Task(
        title=title,
        project_id=project.id,
        task_status_id=status.id,
        guild_id=project.guild_id,
        created_by_id=created_by_id,
        due_date=due_date,
        start_date=start_date,
        priority=priority,
    )
    session.add(task)
    await session.commit()
    await session.refresh(task)
    return task


async def _assign(session, task, user_id):
    """Assign ``task`` to ``user_id``. TaskAssignee has no guild_id, so route
    the write into the task's guild schema explicitly."""
    from app.db.session import set_rls_context

    await set_rls_context(session, user_id=user_id, guild_id=task.guild_id)
    session.add(TaskAssignee(task_id=task.id, user_id=user_id))
    await session.commit()


async def _setup_guild_with_project(session, user, *, guild_name="Test Guild"):
    """Create a guild, membership, initiative, and project for the user."""
    guild = await create_guild(session, creator=user, name=guild_name)
    await create_guild_membership(session, user=user, guild=guild, role=GuildRole.admin)
    initiative = await create_initiative(session, guild, user, name="Initiative")
    project = await create_project(session, initiative, user, name="Project")
    return guild, initiative, project


@pytest.mark.integration
async def test_list_my_tasks_returns_assigned(
    client: AsyncClient, session: AsyncSession
):
    """GET /me/tasks returns tasks assigned to the current user."""
    user = await create_user(session, email="user@example.com")
    guild, _, project = await _setup_guild_with_project(session, user)

    task1 = await _create_task(session, project, "Assigned 1", created_by_id=user.id)
    task2 = await _create_task(session, project, "Assigned 2", created_by_id=user.id)
    await _assign(session, task1, user.id)
    await _assign(session, task2, user.id)

    headers = await get_guild_headers(session, guild, user)
    response = await client.get("/api/v1/me/tasks", headers=headers)

    assert response.status_code == 200, response.text
    task_ids = {t["id"] for t in response.json()["items"]}
    assert task1.id in task_ids
    assert task2.id in task_ids


@pytest.mark.integration
async def test_list_my_tasks_excludes_unassigned_and_others(
    client: AsyncClient, session: AsyncSession
):
    """GET /me/tasks excludes tasks not assigned to the caller — including a
    task the caller created but isn't assigned to, and a task assigned to
    someone else."""
    user = await create_user(session, email="user@example.com")
    other = await create_user(session, email="other@example.com")
    guild, _, project = await _setup_guild_with_project(session, user)
    await create_guild_membership(session, user=other, guild=guild)

    mine = await _create_task(session, project, "Mine", created_by_id=user.id)
    await _assign(session, mine, user.id)

    # Created by the caller but assigned to nobody — the assigned view must skip it.
    created_not_assigned = await _create_task(
        session, project, "Created not assigned", created_by_id=user.id
    )

    # Assigned to someone else — must not appear for the caller.
    others = await _create_task(session, project, "Others", created_by_id=user.id)
    await _assign(session, others, other.id)

    headers = await get_guild_headers(session, guild, user)
    response = await client.get("/api/v1/me/tasks", headers=headers)

    assert response.status_code == 200, response.text
    task_ids = {t["id"] for t in response.json()["items"]}
    assert mine.id in task_ids
    assert created_not_assigned.id not in task_ids
    assert others.id not in task_ids


@pytest.mark.integration
async def test_list_my_tasks_priority_filter(
    client: AsyncClient, session: AsyncSession
):
    """GET /me/tasks respects priority filters."""
    user = await create_user(session, email="user@example.com")
    guild, _, project = await _setup_guild_with_project(session, user)

    high = await _create_task(session, project, "High", created_by_id=user.id)
    high.priority = TaskPriority.high
    session.add(high)
    low = await _create_task(session, project, "Low", created_by_id=user.id)
    low.priority = TaskPriority.low
    session.add(low)
    await session.commit()
    await _assign(session, high, user.id)
    await _assign(session, low, user.id)

    headers = await get_guild_headers(session, guild, user)
    conditions = json.dumps([{"field": "priority", "op": "in_", "value": ["high"]}])
    response = await client.get(
        f"/api/v1/me/tasks?conditions={conditions}", headers=headers
    )

    assert response.status_code == 200, response.text
    task_ids = {t["id"] for t in response.json()["items"]}
    assert high.id in task_ids
    assert low.id not in task_ids


@pytest.mark.integration
async def test_list_my_tasks_guild_ids_filter(
    client: AsyncClient, session: AsyncSession
):
    """GET /me/tasks with the guild_ids filter restricts to the named guilds.

    Regression: the frontend previously sent ``field: "guild_id"`` (singular)
    but the endpoint extracts ``guild_ids`` (plural, mirroring initiative_ids);
    the singular silently no-op'd and tasks from every guild leaked in.
    """
    user = await create_user(session, email="user@example.com")
    guild1, _, project1 = await _setup_guild_with_project(
        session, user, guild_name="Guild 1"
    )
    guild2, _, project2 = await _setup_guild_with_project(
        session, user, guild_name="Guild 2"
    )

    task1 = await _create_task(
        session, project1, "Task in Guild 1", created_by_id=user.id
    )
    task2 = await _create_task(
        session, project2, "Task in Guild 2", created_by_id=user.id
    )
    await _assign(session, task1, user.id)
    await _assign(session, task2, user.id)

    headers = await get_guild_headers(session, guild1, user)

    def keyed(resp):
        # Task ids are per-guild (per-schema); key by (guild_id, id).
        return {(t["guild_id"], t["id"]) for t in resp.json()["items"]}

    # No filter: assigned tasks from BOTH guilds are aggregated.
    response = await client.get("/api/v1/me/tasks", headers=headers)
    assert response.status_code == 200, response.text
    found = keyed(response)
    assert (guild1.id, task1.id) in found
    assert (guild2.id, task2.id) in found

    # Filtered to guild1: only guild1's task.
    conditions = json.dumps([{"field": "guild_ids", "op": "in_", "value": [guild1.id]}])
    response = await client.get(
        f"/api/v1/me/tasks?conditions={conditions}", headers=headers
    )
    assert response.status_code == 200, response.text
    found = keyed(response)
    assert (guild1.id, task1.id) in found
    assert (guild2.id, task2.id) not in found


@pytest.mark.integration
async def test_list_my_tasks_pagination(client: AsyncClient, session: AsyncSession):
    """GET /me/tasks supports pagination."""
    user = await create_user(session, email="user@example.com")
    guild, _, project = await _setup_guild_with_project(session, user)

    for i in range(3):
        task = await _create_task(session, project, f"Task {i}", created_by_id=user.id)
        await _assign(session, task, user.id)

    headers = await get_guild_headers(session, guild, user)

    # Page 1 with page_size=2
    response = await client.get("/api/v1/me/tasks?page=1&page_size=2", headers=headers)
    assert response.status_code == 200, response.text
    data = response.json()
    assert len(data["items"]) == 2
    assert data["total_count"] == 3
    assert data["has_next"] is True

    # Page 2
    response = await client.get("/api/v1/me/tasks?page=2&page_size=2", headers=headers)
    assert response.status_code == 200, response.text
    data = response.json()
    assert len(data["items"]) == 1
    assert data["has_next"] is False


@pytest.mark.integration
async def test_list_my_tasks_date_group_sorted_across_guilds(
    client: AsyncClient, session: AsyncSession
):
    """GET /me/tasks sorts by date_group then due_date across ALL guilds.

    Regression: per-guild SQL ordering was concatenated in guild-id order, so a
    later guild's "today" task could appear after an earlier guild's "later"
    task. The merged set must be globally re-sorted before pagination.
    """
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    overdue = now - timedelta(days=2)
    this_week = now + timedelta(days=3)
    later = now + timedelta(days=60)

    user = await create_user(session, email="user@example.com")
    guild1, _, project1 = await _setup_guild_with_project(
        session, user, guild_name="Guild 1"
    )
    guild2, _, project2 = await _setup_guild_with_project(
        session, user, guild_name="Guild 2"
    )

    # Interleave date groups so any per-guild-only ordering is detectably wrong:
    # guild1 holds overdue + later; guild2 holds today + this-week.
    g1_overdue = await _create_task(
        session, project1, "g1 overdue", created_by_id=user.id, due_date=overdue
    )
    g1_later = await _create_task(
        session, project1, "g1 later", created_by_id=user.id, due_date=later
    )
    # "Today" via start_date (start <= today → group 1) rather than a narrow
    # future due_date, so the classification is stable at any time of day —
    # including right around midnight UTC.
    g2_today = await _create_task(
        session, project2, "g2 today", created_by_id=user.id, start_date=now
    )
    g2_week = await _create_task(
        session, project2, "g2 this week", created_by_id=user.id, due_date=this_week
    )
    for task in (g1_overdue, g1_later, g2_today, g2_week):
        await _assign(session, task, user.id)

    headers = await get_guild_headers(session, guild1, user)
    sorting = json.dumps(
        [{"field": "date_group", "dir": "asc"}, {"field": "due_date", "dir": "asc"}]
    )
    response = await client.get(
        f"/api/v1/me/tasks?sorting={sorting}&tz=UTC", headers=headers
    )
    assert response.status_code == 200, response.text
    titles = [t["title"] for t in response.json()["items"]]
    # Overdue → today → this week → later, regardless of which guild owns each.
    assert titles == ["g1 overdue", "g2 today", "g2 this week", "g1 later"]


@pytest.mark.integration
async def test_list_my_tasks_priority_sorted_desc_across_guilds(
    client: AsyncClient, session: AsyncSession
):
    """GET /me/tasks sorts by priority across guilds in PG enum order (low→urgent),
    not alphabetically — descending therefore yields urgent → high → medium → low.
    """
    user = await create_user(session, email="user@example.com")
    guild1, _, project1 = await _setup_guild_with_project(
        session, user, guild_name="Guild 1"
    )
    guild2, _, project2 = await _setup_guild_with_project(
        session, user, guild_name="Guild 2"
    )

    # Split priorities across both guilds so per-guild-only ordering is wrong.
    g1_low = await _create_task(
        session, project1, "low", created_by_id=user.id, priority=TaskPriority.low
    )
    g1_high = await _create_task(
        session, project1, "high", created_by_id=user.id, priority=TaskPriority.high
    )
    g2_medium = await _create_task(
        session, project2, "medium", created_by_id=user.id, priority=TaskPriority.medium
    )
    g2_urgent = await _create_task(
        session, project2, "urgent", created_by_id=user.id, priority=TaskPriority.urgent
    )
    for task in (g1_low, g1_high, g2_medium, g2_urgent):
        await _assign(session, task, user.id)

    headers = await get_guild_headers(session, guild1, user)
    sorting = json.dumps([{"field": "priority", "dir": "desc"}])
    response = await client.get(f"/api/v1/me/tasks?sorting={sorting}", headers=headers)
    assert response.status_code == 200, response.text
    titles = [t["title"] for t in response.json()["items"]]
    assert titles == ["urgent", "high", "medium", "low"]
