"""
Integration tests for task endpoints.

Tests the task API endpoints at /api/v1/tasks including:
- Listing tasks
- Creating tasks
- Updating tasks
- Deleting tasks
- Moving tasks
- Duplicating tasks
- Managing subtasks
- Task reordering
"""

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.guild import GuildRole
from app.models.initiative import InitiativeRole
from tests.factories import (
    create_guild,
    create_guild_membership,
    create_user,
    get_guild_headers,
)


async def _create_initiative(session, guild, user):
    """Helper to create an initiative."""
    from tests.factories import create_initiative as factory_create_initiative

    initiative = await factory_create_initiative(
        session, guild, user, name="Test Initiative"
    )
    return initiative


async def _create_project(session, initiative, owner):
    """Helper to create a project."""
    from tests.factories import create_project as factory_create_project

    project = await factory_create_project(
        session, initiative, owner, name="Test Project"
    )
    return project


async def _create_task(session, project, title="Test Task"):
    """Helper to create a task."""
    from app.models.task import Task
    from app.services import task_statuses as task_statuses_service

    # Ensure default statuses exist and get the default status
    await task_statuses_service.ensure_default_statuses(session, project.id)
    status = await task_statuses_service.get_default_status(session, project.id)

    task = Task(
        title=title,
        project_id=project.id,
        task_status_id=status.id,
    )
    session.add(task)
    await session.commit()
    await session.refresh(task)
    return task


@pytest.mark.integration
async def test_list_tasks_requires_guild_context(
    client: AsyncClient, session: AsyncSession
):
    """Test that listing tasks requires guild context."""
    user = await create_user(session)
    guild = await create_guild(session)
    await create_guild_membership(session, user=user, guild=guild)

    # Request without X-Guild-ID header
    headers = {"Authorization": f"Bearer fake_token_{user.id}"}
    response = await client.get("/api/v1/tasks/", headers=headers)

    assert response.status_code == 403


@pytest.mark.integration
async def test_list_tasks_in_project(client: AsyncClient, session: AsyncSession):
    """Test listing tasks filtered by project."""
    user = await create_user(session, email="user@example.com")
    guild = await create_guild(session)
    await create_guild_membership(session, user=user, guild=guild)

    initiative = await _create_initiative(session, guild, user)
    project = await _create_project(session, initiative, user)
    task1 = await _create_task(session, project, "Task 1")
    task2 = await _create_task(session, project, "Task 2")

    headers = get_guild_headers(guild, user)
    response = await client.get(
        f"/api/v1/tasks/?project_id={project.id}", headers=headers
    )

    assert response.status_code == 200
    data = response.json()
    task_ids = {t["id"] for t in data}
    assert task1.id in task_ids
    assert task2.id in task_ids


@pytest.mark.integration
async def test_create_task(client: AsyncClient, session: AsyncSession):
    """Test creating a new task."""
    from app.services import task_statuses as task_statuses_service

    user = await create_user(session, email="user@example.com")
    guild = await create_guild(session)
    await create_guild_membership(session, user=user, guild=guild)

    initiative = await _create_initiative(session, guild, user)
    project = await _create_project(session, initiative, user)

    # Create a task status
    await task_statuses_service.ensure_default_statuses(session, project.id)
    status = await task_statuses_service.get_default_status(session, project.id)
    await session.commit()

    headers = get_guild_headers(guild, user)
    payload = {
        "title": "New Task",
        "description": "Task description",
        "project_id": project.id,
        "task_status_id": status.id,
        "priority": 2,
    }

    response = await client.post("/api/v1/tasks/", headers=headers, json=payload)

    assert response.status_code == 201
    data = response.json()
    assert data["title"] == "New Task"
    assert data["description"] == "Task description"
    assert data["priority"] == 2


@pytest.mark.integration
async def test_create_task_requires_project_access(
    client: AsyncClient, session: AsyncSession
):
    """Test that creating tasks requires project access."""
    owner = await create_user(session, email="owner@example.com")
    outsider = await create_user(session, email="outsider@example.com")
    guild = await create_guild(session)
    await create_guild_membership(session, user=owner, guild=guild)
    await create_guild_membership(session, user=outsider, guild=guild)

    initiative = await _create_initiative(session, guild, owner)
    project = await _create_project(session, initiative, owner)

    from app.services import task_statuses as task_statuses_service
    await task_statuses_service.ensure_default_statuses(session, project.id)
    status = await task_statuses_service.get_default_status(session, project.id)
    await session.commit()

    headers = get_guild_headers(guild, outsider)
    payload = {
        "title": "Forbidden Task",
        "project_id": project.id,
        "task_status_id": status.id,
    }

    response = await client.post("/api/v1/tasks/", headers=headers, json=payload)

    assert response.status_code == 403


@pytest.mark.integration
async def test_get_task_by_id(client: AsyncClient, session: AsyncSession):
    """Test getting a task by ID."""
    user = await create_user(session, email="user@example.com")
    guild = await create_guild(session)
    await create_guild_membership(session, user=user, guild=guild)

    initiative = await _create_initiative(session, guild, user)
    project = await _create_project(session, initiative, user)
    task = await _create_task(session, project)

    headers = get_guild_headers(guild, user)
    response = await client.get(f"/api/v1/tasks/{task.id}", headers=headers)

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == task.id
    assert data["title"] == task.title


@pytest.mark.integration
async def test_get_task_not_found(client: AsyncClient, session: AsyncSession):
    """Test getting non-existent task."""
    user = await create_user(session, email="user@example.com")
    guild = await create_guild(session)
    await create_guild_membership(session, user=user, guild=guild)

    headers = get_guild_headers(guild, user)
    response = await client.get("/api/v1/tasks/99999", headers=headers)

    assert response.status_code == 404


@pytest.mark.integration
async def test_update_task(client: AsyncClient, session: AsyncSession):
    """Test updating a task."""
    user = await create_user(session, email="user@example.com")
    guild = await create_guild(session)
    await create_guild_membership(session, user=user, guild=guild)

    initiative = await _create_initiative(session, guild, user)
    project = await _create_project(session, initiative, user)
    task = await _create_task(session, project)

    headers = get_guild_headers(guild, user)
    payload = {"title": "Updated Title", "description": "Updated description"}

    response = await client.patch(
        f"/api/v1/tasks/{task.id}", headers=headers, json=payload
    )

    assert response.status_code == 200
    data = response.json()
    assert data["title"] == "Updated Title"
    assert data["description"] == "Updated description"


@pytest.mark.integration
async def test_update_task_without_permission_forbidden(
    client: AsyncClient, session: AsyncSession
):
    """Test that users without permission cannot update tasks."""
    owner = await create_user(session, email="owner@example.com")
    outsider = await create_user(session, email="outsider@example.com")
    guild = await create_guild(session)
    await create_guild_membership(session, user=owner, guild=guild)
    await create_guild_membership(session, user=outsider, guild=guild)

    initiative = await _create_initiative(session, guild, owner)
    project = await _create_project(session, initiative, owner)
    task = await _create_task(session, project)

    headers = get_guild_headers(guild, outsider)
    payload = {"title": "Hacked Title"}

    response = await client.patch(
        f"/api/v1/tasks/{task.id}", headers=headers, json=payload
    )

    assert response.status_code == 403


@pytest.mark.integration
async def test_delete_task(client: AsyncClient, session: AsyncSession):
    """Test deleting a task."""
    user = await create_user(session, email="user@example.com")
    guild = await create_guild(session)
    await create_guild_membership(session, user=user, guild=guild)

    initiative = await _create_initiative(session, guild, user)
    project = await _create_project(session, initiative, user)
    task = await _create_task(session, project)

    headers = get_guild_headers(guild, user)
    response = await client.delete(f"/api/v1/tasks/{task.id}", headers=headers)

    assert response.status_code == 204


@pytest.mark.integration
async def test_delete_task_without_permission_forbidden(
    client: AsyncClient, session: AsyncSession
):
    """Test that users without permission cannot delete tasks."""
    owner = await create_user(session, email="owner@example.com")
    outsider = await create_user(session, email="outsider@example.com")
    guild = await create_guild(session)
    await create_guild_membership(session, user=owner, guild=guild)
    await create_guild_membership(session, user=outsider, guild=guild)

    initiative = await _create_initiative(session, guild, owner)
    project = await _create_project(session, initiative, owner)
    task = await _create_task(session, project)

    headers = get_guild_headers(guild, outsider)
    response = await client.delete(f"/api/v1/tasks/{task.id}", headers=headers)

    assert response.status_code == 403


@pytest.mark.integration
async def test_assign_user_to_task(client: AsyncClient, session: AsyncSession):
    """Test assigning a user to a task."""
    user = await create_user(session, email="user@example.com")
    assignee = await create_user(session, email="assignee@example.com")
    guild = await create_guild(session)
    await create_guild_membership(session, user=user, guild=guild)
    await create_guild_membership(session, user=assignee, guild=guild)

    initiative = await _create_initiative(session, guild, user)

    # Add assignee to initiative
    from app.models.initiative import InitiativeMember
    session.add(InitiativeMember(
        initiative_id=initiative.id,
        user_id=assignee.id,
        role=InitiativeRole.member,
    ))
    await session.commit()

    project = await _create_project(session, initiative, user)
    task = await _create_task(session, project)

    headers = get_guild_headers(guild, user)
    payload = {"assignee_ids": [assignee.id]}

    response = await client.patch(
        f"/api/v1/tasks/{task.id}", headers=headers, json=payload
    )

    assert response.status_code == 200
    data = response.json()
    assignee_ids = {a["id"] for a in data["assignees"]}
    assert assignee.id in assignee_ids


@pytest.mark.integration
async def test_move_task_to_different_project(
    client: AsyncClient, session: AsyncSession
):
    """Test moving a task to a different project."""
    user = await create_user(session, email="user@example.com")
    guild = await create_guild(session)
    await create_guild_membership(session, user=user, guild=guild)

    initiative = await _create_initiative(session, guild, user)
    project1 = await _create_project(session, initiative, user)
    project2 = await _create_project(session, initiative, user)
    project2.name = "Project 2"
    session.add(project2)
    await session.commit()

    task = await _create_task(session, project1)

    from app.services import task_statuses as task_statuses_service
    await task_statuses_service.ensure_default_statuses(session, project2.id)
    target_status = await task_statuses_service.get_default_status(session, project2.id)
    await session.commit()

    headers = get_guild_headers(guild, user)
    payload = {
        "target_project_id": project2.id,
        "target_status_id": target_status.id,
    }

    response = await client.post(
        f"/api/v1/tasks/{task.id}/move", headers=headers, json=payload
    )

    assert response.status_code == 200
    data = response.json()
    assert data["project_id"] == project2.id


@pytest.mark.integration
async def test_duplicate_task(client: AsyncClient, session: AsyncSession):
    """Test duplicating a task."""
    user = await create_user(session, email="user@example.com")
    guild = await create_guild(session)
    await create_guild_membership(session, user=user, guild=guild)

    initiative = await _create_initiative(session, guild, user)
    project = await _create_project(session, initiative, user)
    task = await _create_task(session, project, "Original Task")

    headers = get_guild_headers(guild, user)
    response = await client.post(
        f"/api/v1/tasks/{task.id}/duplicate", headers=headers, json={}
    )

    assert response.status_code == 201
    data = response.json()
    assert data["title"] == "Original Task (copy)"
    assert data["project_id"] == task.project_id
    assert data["id"] != task.id


@pytest.mark.integration
async def test_create_subtask(client: AsyncClient, session: AsyncSession):
    """Test creating a subtask."""
    user = await create_user(session, email="user@example.com")
    guild = await create_guild(session)
    await create_guild_membership(session, user=user, guild=guild)

    initiative = await _create_initiative(session, guild, user)
    project = await _create_project(session, initiative, user)
    task = await _create_task(session, project)

    headers = get_guild_headers(guild, user)
    payload = {"content": "Subtask content"}

    response = await client.post(
        f"/api/v1/tasks/{task.id}/subtasks", headers=headers, json=payload
    )

    assert response.status_code == 201
    data = response.json()
    assert data["content"] == "Subtask content"
    assert data["task_id"] == task.id
    assert data["is_completed"] is False


@pytest.mark.integration
async def test_list_subtasks(client: AsyncClient, session: AsyncSession):
    """Test listing subtasks."""
    from app.models.task import Subtask

    user = await create_user(session, email="user@example.com")
    guild = await create_guild(session)
    await create_guild_membership(session, user=user, guild=guild)

    initiative = await _create_initiative(session, guild, user)
    project = await _create_project(session, initiative, user)
    task = await _create_task(session, project)

    # Create some subtasks
    subtask1 = Subtask(task_id=task.id, content="Subtask 1", position=0)
    subtask2 = Subtask(task_id=task.id, content="Subtask 2", position=1)
    session.add(subtask1)
    session.add(subtask2)
    await session.commit()

    headers = get_guild_headers(guild, user)
    response = await client.get(f"/api/v1/tasks/{task.id}/subtasks", headers=headers)

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    contents = {s["content"] for s in data}
    assert "Subtask 1" in contents
    assert "Subtask 2" in contents


@pytest.mark.integration
async def test_reorder_subtasks(client: AsyncClient, session: AsyncSession):
    """Test reordering subtasks."""
    from app.models.task import Subtask

    user = await create_user(session, email="user@example.com")
    guild = await create_guild(session)
    await create_guild_membership(session, user=user, guild=guild)

    initiative = await _create_initiative(session, guild, user)
    project = await _create_project(session, initiative, user)
    task = await _create_task(session, project)

    # Create subtasks
    subtask1 = Subtask(task_id=task.id, content="Subtask 1", position=0)
    subtask2 = Subtask(task_id=task.id, content="Subtask 2", position=1)
    session.add(subtask1)
    session.add(subtask2)
    await session.commit()
    await session.refresh(subtask1)
    await session.refresh(subtask2)

    headers = get_guild_headers(guild, user)
    payload = {"subtask_ids": [subtask2.id, subtask1.id]}

    response = await client.put(
        f"/api/v1/tasks/{task.id}/subtasks/order", headers=headers, json=payload
    )

    assert response.status_code == 200
    data = response.json()
    ordered_ids = [s["id"] for s in data]
    assert ordered_ids == [subtask2.id, subtask1.id]


@pytest.mark.integration
async def test_reorder_tasks(client: AsyncClient, session: AsyncSession):
    """Test reordering tasks within a project."""
    user = await create_user(session, email="user@example.com")
    guild = await create_guild(session)
    await create_guild_membership(session, user=user, guild=guild)

    initiative = await _create_initiative(session, guild, user)
    project = await _create_project(session, initiative, user)
    task1 = await _create_task(session, project, "Task 1")
    task2 = await _create_task(session, project, "Task 2")
    task3 = await _create_task(session, project, "Task 3")

    headers = get_guild_headers(guild, user)
    payload = {"task_ids": [task3.id, task1.id, task2.id]}

    response = await client.post("/api/v1/tasks/reorder", headers=headers, json=payload)

    assert response.status_code == 200
    data = response.json()
    ordered_ids = [t["id"] for t in data]
    assert ordered_ids == [task3.id, task1.id, task2.id]


@pytest.mark.integration
async def test_task_guild_isolation(client: AsyncClient, session: AsyncSession):
    """Test that tasks are isolated by guild."""
    user = await create_user(session, email="user@example.com")
    guild1 = await create_guild(session, name="Guild 1")
    guild2 = await create_guild(session, name="Guild 2")
    await create_guild_membership(session, user=user, guild=guild1, role=GuildRole.admin)
    await create_guild_membership(session, user=user, guild=guild2, role=GuildRole.admin)

    initiative1 = await _create_initiative(session, guild1, user)
    project1 = await _create_project(session, initiative1, user)
    task1 = await _create_task(session, project1)

    # Cannot access guild1 task with guild2 context
    headers2 = get_guild_headers(guild2, user)
    response2 = await client.get(f"/api/v1/tasks/{task1.id}", headers=headers2)

    assert response2.status_code == 404


@pytest.mark.integration
async def test_list_my_tasks(client: AsyncClient, session: AsyncSession):
    """Test listing tasks assigned to current user."""
    from app.models.task import TaskAssignee

    user = await create_user(session, email="user@example.com")
    other_user = await create_user(session, email="other@example.com")
    guild = await create_guild(session)
    await create_guild_membership(session, user=user, guild=guild)
    await create_guild_membership(session, user=other_user, guild=guild)

    initiative = await _create_initiative(session, guild, user)
    project = await _create_project(session, initiative, user)

    # Create tasks
    my_task = await _create_task(session, project, "My Task")
    other_task = await _create_task(session, project, "Other Task")

    # Assign tasks
    session.add(TaskAssignee(task_id=my_task.id, user_id=user.id))
    session.add(TaskAssignee(task_id=other_task.id, user_id=other_user.id))
    await session.commit()

    headers = get_guild_headers(guild, user)
    response = await client.get("/api/v1/tasks/?assignee_id=me", headers=headers)

    assert response.status_code == 200
    data = response.json()
    task_ids = {t["id"] for t in data}
    assert my_task.id in task_ids
    assert other_task.id not in task_ids


@pytest.mark.integration
async def test_filter_tasks_by_status(client: AsyncClient, session: AsyncSession):
    """Test filtering tasks by status."""
    from app.services import task_statuses as task_statuses_service

    user = await create_user(session, email="user@example.com")
    guild = await create_guild(session)
    await create_guild_membership(session, user=user, guild=guild)

    initiative = await _create_initiative(session, guild, user)
    project = await _create_project(session, initiative, user)

    # Create statuses
    statuses = await task_statuses_service.ensure_default_statuses(session, project.id)
    todo_status = next(s for s in statuses if s.is_default)
    done_status = next(s for s in statuses if s.name == "Done")
    await session.commit()

    # Create tasks with different statuses
    from app.models.task import Task
    task1 = Task(
        title="Todo Task", project_id=project.id, task_status_id=todo_status.id
    )
    task2 = Task(
        title="Done Task", project_id=project.id, task_status_id=done_status.id
    )
    session.add(task1)
    session.add(task2)
    await session.commit()

    headers = get_guild_headers(guild, user)
    response = await client.get(
        f"/api/v1/tasks/?project_id={project.id}&task_status_id={todo_status.id}",
        headers=headers,
    )

    assert response.status_code == 200
    data = response.json()
    task_titles = {t["title"] for t in data}
    assert "Todo Task" in task_titles
    assert "Done Task" not in task_titles
