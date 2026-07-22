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

import json
from zoneinfo import ZoneInfo

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.guild import GuildRole
from app.testing.factories import (
    create_guild,
    create_guild_membership,
    create_initiative,
    create_project,
    create_user,
)


async def _create_task(session, project, title="Test Task"):
    """Helper to create a task."""
    from app.models.tenant.task import Task
    from app.services.tenant import task_statuses as task_statuses_service

    # Ensure default statuses exist and get the default status
    await task_statuses_service.ensure_default_statuses(session, project.id)
    status = await task_statuses_service.get_default_status(session, project.id)

    task = Task(
        title=title,
        project_id=project.id,
        task_status_id=status.id,
        guild_id=project.guild_id,
    )
    session.add(task)
    await session.commit()
    await session.refresh(task)
    return task


@pytest.mark.integration
async def test_list_tasks_in_project(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Test listing tasks filtered by project."""
    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    task1 = await _create_task(session, a.project, "Task 1")
    task2 = await _create_task(session, a.project, "Task 2")

    conditions = json.dumps(
        [{"field": "project_id", "op": "eq", "value": a.project.id}]
    )
    response = await client.get(
        a.g(f"/tasks/?conditions={conditions}"), headers=a.headers
    )

    assert response.status_code == 200
    data = response.json()["items"]
    task_ids = {t["id"] for t in data}
    assert task1.id in task_ids
    assert task2.id in task_ids


@pytest.mark.integration
async def test_list_tasks_guild_admin_sees_unjoined_project(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """A guild admin sees every project's tasks, even ones they never joined.

    Regression: the admin is NOT an initiative member of the project's
    initiative and holds no explicit/role DAC permission on the project (the
    "Barovia Arc" scenario). They must still list its tasks — guild admins have
    full guild access. Previously ``_allowed_project_ids`` lacked a guild-admin
    branch, so the admin got "no results".
    """
    # ``owner`` (a plain guild member) builds the initiative + project, so the
    # admin is neither a member nor a permission holder.
    owner = await acting_user(
        guild_role=GuildRole.member, initiative=True, project=True
    )
    admin = await acting_user(guild_role=GuildRole.admin, guild=owner.guild)

    task1 = await _create_task(session, owner.project, "Hidden Task 1")
    task2 = await _create_task(session, owner.project, "Hidden Task 2")

    conditions = json.dumps(
        [{"field": "project_id", "op": "eq", "value": owner.project.id}]
    )
    response = await client.get(
        admin.g(f"/tasks/?conditions={conditions}"), headers=admin.headers
    )

    assert response.status_code == 200
    task_ids = {t["id"] for t in response.json()["items"]}
    assert task1.id in task_ids
    assert task2.id in task_ids


@pytest.mark.integration
async def test_create_task(client: AsyncClient, session: AsyncSession, acting_user):
    """Test creating a new task."""
    from app.services.tenant import task_statuses as task_statuses_service

    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)

    # Create a task status
    await task_statuses_service.ensure_default_statuses(session, a.project.id)
    status = await task_statuses_service.get_default_status(session, a.project.id)
    await session.commit()

    payload = {
        "title": "New Task",
        "description": "Task description",
        "project_id": a.project.id,
        "task_status_id": status.id,
        "priority": "high",
    }

    response = await client.post(a.g("/tasks/"), headers=a.headers, json=payload)

    assert response.status_code == 201
    data = response.json()
    assert data["title"] == "New Task"
    assert data["description"] == "Task description"
    assert data["priority"] == "high"


@pytest.mark.integration
async def test_create_task_with_status(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """A non-default ``task_status_id`` is honored on create."""
    from app.services.tenant import task_statuses as task_statuses_service

    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    await task_statuses_service.ensure_default_statuses(session, a.project.id)
    statuses = await task_statuses_service.list_statuses(session, a.project.id)
    default_status = await task_statuses_service.get_default_status(
        session, a.project.id
    )
    await session.commit()
    non_default = next(s for s in statuses if s.id != default_status.id)

    response = await client.post(
        a.g("/tasks/"),
        headers=a.headers,
        json={
            "title": "Statused Task",
            "project_id": a.project.id,
            "task_status_id": non_default.id,
        },
    )

    assert response.status_code == 201
    assert response.json()["task_status_id"] == non_default.id


@pytest.mark.integration
async def test_create_task_with_tags(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """``tag_ids`` on create attaches the tags in the same request."""
    from app.testing.factories import create_tag

    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    tag1 = await create_tag(session, a.guild, name="urgent")
    tag2 = await create_tag(session, a.guild, name="backend")

    response = await client.post(
        a.g("/tasks/"),
        headers=a.headers,
        json={
            "title": "Tagged Task",
            "project_id": a.project.id,
            "tag_ids": [tag1.id, tag2.id],
        },
    )

    assert response.status_code == 201
    returned_tag_ids = {t["id"] for t in response.json()["tags"]}
    assert returned_tag_ids == {tag1.id, tag2.id}


@pytest.mark.integration
async def test_create_task_with_properties(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """``property_values`` on create attaches custom property values."""
    from app.testing.factories import create_property_definition

    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    text_defn = await create_property_definition(session, a.initiative, name="Notes")

    response = await client.post(
        a.g("/tasks/"),
        headers=a.headers,
        json={
            "title": "Task with props",
            "project_id": a.project.id,
            "property_values": [{"property_id": text_defn.id, "value": "hello"}],
        },
    )

    assert response.status_code == 201
    props = {p["property_id"]: p["value"] for p in response.json()["properties"]}
    assert props[text_defn.id] == "hello"


@pytest.mark.integration
async def test_create_task_with_invalid_tag_id_rolls_back(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """An invalid tag id fails the create and persists no task."""
    from sqlmodel import func, select

    from app.models.tenant.task import Task

    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)

    response = await client.post(
        a.g("/tasks/"),
        headers=a.headers,
        json={
            "title": "Should Not Exist",
            "project_id": a.project.id,
            "tag_ids": [999999],
        },
    )

    assert response.status_code in (400, 404)
    count = (
        await session.exec(
            select(func.count())
            .select_from(Task)
            .where(Task.title == "Should Not Exist")
        )
    ).one()
    assert count == 0


@pytest.mark.integration
async def test_create_task_with_invalid_property_rolls_back(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """A property from another initiative fails the create and persists no task."""
    from sqlmodel import func, select

    from app.models.tenant.task import Task
    from app.testing.factories import create_initiative, create_property_definition

    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    # A definition scoped to a DIFFERENT initiative in the same guild.
    other_initiative = await create_initiative(session, a.guild, a.user)
    foreign_defn = await create_property_definition(
        session, other_initiative, name="Foreign"
    )

    response = await client.post(
        a.g("/tasks/"),
        headers=a.headers,
        json={
            "title": "Bad Prop Task",
            "project_id": a.project.id,
            "property_values": [{"property_id": foreign_defn.id, "value": "x"}],
        },
    )

    assert response.status_code in (400, 404)
    count = (
        await session.exec(
            select(func.count()).select_from(Task).where(Task.title == "Bad Prop Task")
        )
    ).one()
    assert count == 0


@pytest.mark.integration
async def test_update_task_with_tags_and_properties(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """PATCH replaces tags/properties; omitting the keys leaves them unchanged."""
    from app.testing.factories import create_property_definition, create_tag

    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    task = await _create_task(session, a.project)
    tag = await create_tag(session, a.guild, name="review")
    defn = await create_property_definition(session, a.initiative, name="Estimate")

    # Set tags + a property value via PATCH.
    response = await client.patch(
        a.g(f"/tasks/{task.id}"),
        headers=a.headers,
        json={
            "tag_ids": [tag.id],
            "property_values": [{"property_id": defn.id, "value": "later"}],
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert {t["id"] for t in body["tags"]} == {tag.id}
    assert {p["property_id"]: p["value"] for p in body["properties"]}[
        defn.id
    ] == "later"

    # A PATCH that omits the keys must leave tags/properties intact.
    response = await client.patch(
        a.g(f"/tasks/{task.id}"),
        headers=a.headers,
        json={"title": "Renamed"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "Renamed"
    assert {t["id"] for t in body["tags"]} == {tag.id}
    assert {p["property_id"] for p in body["properties"]} == {defn.id}

    # An explicit empty list clears them.
    response = await client.patch(
        a.g(f"/tasks/{task.id}"),
        headers=a.headers,
        json={"tag_ids": [], "property_values": []},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["tags"] == []
    assert body["properties"] == []


@pytest.mark.integration
async def test_create_task_requires_project_access(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Test that creating tasks requires project access."""
    owner = await acting_user(
        guild_role=GuildRole.member, initiative=True, project=True
    )
    # ``outsider`` is a guild member but NOT an initiative member.
    outsider = await acting_user(guild_role=GuildRole.member, guild=owner.guild)

    from app.services.tenant import task_statuses as task_statuses_service

    await task_statuses_service.ensure_default_statuses(session, owner.project.id)
    status = await task_statuses_service.get_default_status(session, owner.project.id)
    await session.commit()

    payload = {
        "title": "Forbidden Task",
        "project_id": owner.project.id,
        "task_status_id": status.id,
    }

    response = await client.post(
        outsider.g("/tasks/"), headers=outsider.headers, json=payload
    )

    assert (
        response.status_code == 404
    )  # RLS hides the content resource from a non-initiative-member (404, not 403)


@pytest.mark.integration
async def test_get_task_by_id(client: AsyncClient, session: AsyncSession, acting_user):
    """Test getting a task by ID."""
    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    task = await _create_task(session, a.project)

    response = await client.get(a.g(f"/tasks/{task.id}"), headers=a.headers)

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == task.id
    assert data["title"] == task.title


@pytest.mark.integration
async def test_get_task_not_found(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Test getting non-existent task."""
    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)

    response = await client.get(a.g("/tasks/99999"), headers=a.headers)

    assert response.status_code == 404


@pytest.mark.integration
async def test_update_task(client: AsyncClient, session: AsyncSession, acting_user):
    """Test updating a task."""
    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    task = await _create_task(session, a.project)

    payload = {"title": "Updated Title", "description": "Updated description"}

    response = await client.patch(
        a.g(f"/tasks/{task.id}"), headers=a.headers, json=payload
    )

    assert response.status_code == 200
    data = response.json()
    assert data["title"] == "Updated Title"
    assert data["description"] == "Updated description"


@pytest.mark.integration
async def test_update_task_without_permission_forbidden(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Test that users without permission cannot update tasks."""
    owner = await acting_user(
        guild_role=GuildRole.member, initiative=True, project=True
    )
    outsider = await acting_user(guild_role=GuildRole.member, guild=owner.guild)
    task = await _create_task(session, owner.project)

    payload = {"title": "Hacked Title"}

    response = await client.patch(
        outsider.g(f"/tasks/{task.id}"), headers=outsider.headers, json=payload
    )

    assert (
        response.status_code == 404
    )  # RLS hides the content resource from a non-initiative-member (404, not 403)


@pytest.mark.integration
async def test_delete_task(client: AsyncClient, session: AsyncSession, acting_user):
    """Test deleting a task."""
    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    task = await _create_task(session, a.project)

    response = await client.delete(a.g(f"/tasks/{task.id}"), headers=a.headers)

    assert response.status_code == 204


@pytest.mark.integration
async def test_delete_task_without_permission_forbidden(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Test that users without permission cannot delete tasks."""
    owner = await acting_user(
        guild_role=GuildRole.member, initiative=True, project=True
    )
    outsider = await acting_user(guild_role=GuildRole.member, guild=owner.guild)
    task = await _create_task(session, owner.project)

    response = await client.delete(
        outsider.g(f"/tasks/{task.id}"), headers=outsider.headers
    )

    assert (
        response.status_code == 404
    )  # RLS hides the content resource from a non-initiative-member (404, not 403)


@pytest.mark.integration
async def test_assign_user_to_task(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Test assigning a user to a task."""
    user = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    # Add assignee to the initiative as a member.
    assignee = await acting_user(
        guild_role=GuildRole.member,
        guild=user.guild,
        initiative=user.initiative,
        initiative_role="member",
    )

    task = await _create_task(session, user.project)

    payload = {"assignee_ids": [assignee.user.id]}

    response = await client.patch(
        user.g(f"/tasks/{task.id}"), headers=user.headers, json=payload
    )

    assert response.status_code == 200
    data = response.json()
    assignee_ids = {a["id"] for a in data["assignees"]}
    assert assignee.user.id in assignee_ids


@pytest.mark.integration
async def test_move_task_to_different_project(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Test moving a task to a different project."""
    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    project1 = a.project
    project2 = await create_project(session, a.initiative, a.user, name="Project 2")

    task = await _create_task(session, project1)

    from app.services.tenant import task_statuses as task_statuses_service

    await task_statuses_service.ensure_default_statuses(session, project2.id)
    target_status = await task_statuses_service.get_default_status(session, project2.id)
    await session.commit()

    payload = {
        "target_project_id": project2.id,
        "target_status_id": target_status.id,
    }

    response = await client.post(
        a.g(f"/tasks/{task.id}/move"), headers=a.headers, json=payload
    )

    assert response.status_code == 200
    data = response.json()
    assert data["project_id"] == project2.id


@pytest.mark.integration
async def test_duplicate_task(client: AsyncClient, session: AsyncSession, acting_user):
    """Test duplicating a task."""
    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    task = await _create_task(session, a.project, "Original Task")

    response = await client.post(
        a.g(f"/tasks/{task.id}/duplicate"), headers=a.headers, json={}
    )

    assert response.status_code == 201
    data = response.json()
    assert data["title"] == "Original Task (copy)"
    assert data["project_id"] == task.project_id
    assert data["id"] != task.id


@pytest.mark.integration
async def test_create_subtask(client: AsyncClient, session: AsyncSession, acting_user):
    """Test creating a subtask."""
    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    task = await _create_task(session, a.project)

    payload = {"content": "Subtask content"}

    response = await client.post(
        a.g(f"/tasks/{task.id}/subtasks"), headers=a.headers, json=payload
    )

    assert response.status_code == 201
    data = response.json()
    assert data["content"] == "Subtask content"
    assert data["task_id"] == task.id
    assert data["is_completed"] is False


@pytest.mark.integration
async def test_list_subtasks(client: AsyncClient, session: AsyncSession, acting_user):
    """Test listing subtasks."""
    from app.models.tenant.task import Subtask

    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    task = await _create_task(session, a.project)

    # Create some subtasks
    subtask1 = Subtask(task_id=task.id, content="Subtask 1", position=0)
    subtask2 = Subtask(task_id=task.id, content="Subtask 2", position=1)
    session.add(subtask1)
    session.add(subtask2)
    await session.commit()

    response = await client.get(a.g(f"/tasks/{task.id}/subtasks"), headers=a.headers)

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    contents = {s["content"] for s in data}
    assert "Subtask 1" in contents
    assert "Subtask 2" in contents


@pytest.mark.integration
async def test_reorder_subtasks(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Test reordering subtasks."""
    from app.models.tenant.task import Subtask

    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    task = await _create_task(session, a.project)

    # Create subtasks
    subtask1 = Subtask(task_id=task.id, content="Subtask 1", position=0)
    subtask2 = Subtask(task_id=task.id, content="Subtask 2", position=1)
    session.add(subtask1)
    session.add(subtask2)
    await session.commit()
    await session.refresh(subtask1)
    await session.refresh(subtask2)

    payload = {
        "items": [
            {"id": subtask2.id, "position": 0},
            {"id": subtask1.id, "position": 1},
        ]
    }

    response = await client.put(
        a.g(f"/tasks/{task.id}/subtasks/order"),
        headers=a.headers,
        json=payload,
    )

    assert response.status_code == 200
    data = response.json()
    ordered_ids = [s["id"] for s in data]
    assert ordered_ids == [subtask2.id, subtask1.id]


@pytest.mark.integration
async def test_reorder_tasks(client: AsyncClient, session: AsyncSession, acting_user):
    """Test reordering tasks within a project."""
    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    task1 = await _create_task(session, a.project, "Task 1")
    task2 = await _create_task(session, a.project, "Task 2")
    task3 = await _create_task(session, a.project, "Task 3")

    payload = {
        "project_id": a.project.id,
        "items": [
            {"id": task3.id, "task_status_id": task3.task_status_id, "position": 0},
            {"id": task1.id, "task_status_id": task1.task_status_id, "position": 1},
            {"id": task2.id, "task_status_id": task2.task_status_id, "position": 2},
        ],
    }

    response = await client.post(a.g("/tasks/reorder"), headers=a.headers, json=payload)

    assert response.status_code == 200
    data = response.json()
    ordered_ids = [t["id"] for t in data]
    assert ordered_ids == [task3.id, task1.id, task2.id]


@pytest.mark.unit
def test_reorder_item_rejects_non_finite_position():
    """NaN/±inf would silently defeat the rebalance gap check, so the schema
    rejects them at the boundary."""
    import math

    from pydantic import ValidationError

    from app.schemas.tenant.task import TaskReorderItem

    for bad in (math.nan, math.inf, -math.inf):
        with pytest.raises(ValidationError):
            TaskReorderItem(id=1, task_status_id=1, position=bad)

    # A normal (and a negative) finite position is accepted.
    assert TaskReorderItem(id=1, task_status_id=1, position=1.5).position == 1.5
    assert TaskReorderItem(id=1, task_status_id=1, position=-0.5).position == -0.5


@pytest.mark.integration
async def test_reorder_single_task_returns_only_affected(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """A reorder sends only the moved task and the response is slimmed to it."""
    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    task1 = await _create_task(session, a.project, "Task 1")
    task2 = await _create_task(session, a.project, "Task 2")
    task3 = await _create_task(session, a.project, "Task 3")

    # Anchor task1/task2 at 1 and 2 so task3 can drop between them.
    task1.position = 1.0
    task2.position = 2.0
    task3.position = 3.0
    session.add_all([task1, task2, task3])
    await session.commit()

    payload = {
        "project_id": a.project.id,
        "items": [
            {"id": task3.id, "task_status_id": task3.task_status_id, "position": 1.5},
        ],
    }

    response = await client.post(a.g("/tasks/reorder"), headers=a.headers, json=payload)

    assert response.status_code == 200
    data = response.json()
    # Only the moved task is returned, and its fractional position round-trips.
    assert [t["id"] for t in data] == [task3.id]
    assert data[0]["position"] == 1.5


@pytest.mark.integration
async def test_reorder_rebalances_on_precision_exhaustion(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Colliding positions trigger a project-wide renumber that leaves the
    updated_at of merely-renumbered (not explicitly moved) tasks untouched."""
    from datetime import datetime

    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    task1 = await _create_task(session, a.project, "Task 1")
    task2 = await _create_task(session, a.project, "Task 2")
    task3 = await _create_task(session, a.project, "Task 3")

    # task1/task2 sit one representable step apart, so a midpoint between them
    # rounds onto a neighbor — precision is exhausted at the drop point.
    task1.position = 1.0
    task2.position = 1.0000000001
    task3.position = 5.0
    session.add_all([task1, task2, task3])
    await session.commit()
    task2_updated_before = task2.updated_at

    payload = {
        "project_id": a.project.id,
        # Drop task3 into the exhausted gap (its position collides with task2),
        # which is what triggers the project-wide renumber.
        "items": [
            {
                "id": task3.id,
                "task_status_id": task3.task_status_id,
                "position": 1.0000000001,
            },
        ],
    }

    response = await client.post(a.g("/tasks/reorder"), headers=a.headers, json=payload)

    assert response.status_code == 200
    data = {t["id"]: t for t in response.json()}
    # Rebalanced to evenly spaced integers across the project.
    assert data[task2.id]["position"] == 2.0
    assert data[task3.id]["position"] == 3.0

    # task2 was only renumbered, not explicitly moved -> updated_at must not churn.
    # (Normalize the trailing 'Z' — datetime.fromisoformat rejects it on <3.11.)
    def _parse(ts: str) -> datetime:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))

    assert _parse(data[task2.id]["updated_at"]) == task2_updated_before
    # task3 was explicitly moved -> updated_at advances.
    assert _parse(data[task3.id]["updated_at"]) > task2_updated_before


@pytest.mark.integration
async def test_task_guild_isolation(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Test that tasks are isolated by guild."""
    # First guild (with a workspace) — the actor is admin of it.
    a = await acting_user(guild_role=GuildRole.admin, initiative=True, project=True)
    task1 = await _create_task(session, a.project)

    # A SECOND guild for the SAME user (acting_user always makes a new user, so
    # build the second guild membership with the raw factories reusing a.user).
    guild2 = await create_guild(session, name="Guild 2")
    await create_guild_membership(
        session, user=a.user, guild=guild2, role=GuildRole.admin
    )

    # Cannot access guild1 task with guild2 context
    response2 = await client.get(
        f"/api/v1/g/{guild2.id}/tasks/{task1.id}", headers=a.headers
    )

    assert response2.status_code == 404


@pytest.mark.integration
async def test_list_my_tasks(client: AsyncClient, session: AsyncSession, acting_user):
    """Test listing tasks assigned to current user."""
    from app.models.tenant.task import TaskAssignee

    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    other_user = await create_user(session, email="other@example.com")
    await create_guild_membership(session, user=other_user, guild=a.guild)

    # Create tasks
    my_task = await _create_task(session, a.project, "My Task")
    other_task = await _create_task(session, a.project, "Other Task")

    # Assign tasks
    session.add(TaskAssignee(task_id=my_task.id, user_id=a.user.id))
    session.add(TaskAssignee(task_id=other_task.id, user_id=other_user.id))
    await session.commit()

    conditions = json.dumps([{"field": "assignee_ids", "op": "in_", "value": ["me"]}])
    response = await client.get(
        a.g(f"/tasks/?conditions={conditions}"), headers=a.headers
    )

    assert response.status_code == 200
    data = response.json()["items"]
    task_ids = {t["id"] for t in data}
    assert my_task.id in task_ids
    assert other_task.id not in task_ids


@pytest.mark.integration
async def test_filter_tasks_by_status(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Test filtering tasks by status."""
    from app.services.tenant import task_statuses as task_statuses_service

    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)

    # Create statuses
    statuses = await task_statuses_service.ensure_default_statuses(
        session, a.project.id
    )
    todo_status = next(s for s in statuses if s.is_default)
    done_status = next(s for s in statuses if s.name == "Done")
    await session.commit()

    # Create tasks with different statuses
    from app.models.tenant.task import Task

    task1 = Task(
        title="Todo Task",
        project_id=a.project.id,
        task_status_id=todo_status.id,
        guild_id=a.guild.id,
    )
    task2 = Task(
        title="Done Task",
        project_id=a.project.id,
        task_status_id=done_status.id,
        guild_id=a.guild.id,
    )
    session.add(task1)
    session.add(task2)
    await session.commit()

    conditions = json.dumps(
        [
            {"field": "project_id", "op": "eq", "value": a.project.id},
            {"field": "task_status_id", "op": "in_", "value": [todo_status.id]},
        ]
    )
    response = await client.get(
        a.g(f"/tasks/?conditions={conditions}"),
        headers=a.headers,
    )

    assert response.status_code == 200
    data = response.json()["items"]
    task_titles = {t["title"] for t in data}
    assert "Todo Task" in task_titles
    assert "Done Task" not in task_titles


@pytest.mark.integration
async def test_rolling_recurrence_preserves_due_time(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Test that completing a task with rolling recurrence preserves the original due time."""
    from datetime import datetime, timezone
    from app.models.tenant.task import Task
    from app.services.tenant import task_statuses as task_statuses_service

    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)

    # Create statuses
    statuses = await task_statuses_service.ensure_default_statuses(
        session, a.project.id
    )
    todo_status = next(s for s in statuses if s.is_default)
    done_status = next(s for s in statuses if s.name == "Done")
    await session.commit()

    # Create a task with rolling recurrence due at 17:00
    original_due_time = datetime(2026, 1, 20, 17, 0, 0, tzinfo=timezone.utc)
    recurrence_data = {
        "frequency": "daily",
        "interval": 3,
        "ends": "never",
    }

    task = Task(
        title="Recurring Task",
        project_id=a.project.id,
        task_status_id=todo_status.id,
        guild_id=a.guild.id,
        due_date=original_due_time,
        recurrence=recurrence_data,
        recurrence_strategy="rolling",  # After completion mode
    )
    session.add(task)
    await session.commit()
    await session.refresh(task)

    # Mark the task as done (simulating completion at a different time like 12:34)
    response = await client.patch(
        a.g(f"/tasks/{task.id}"),
        headers=a.headers,
        json={"task_status_id": done_status.id},
    )

    assert response.status_code == 200

    # Fetch all tasks to find the newly created recurring task
    conditions = json.dumps(
        [{"field": "project_id", "op": "eq", "value": a.project.id}]
    )
    response = await client.get(
        a.g(f"/tasks/?conditions={conditions}"), headers=a.headers
    )
    assert response.status_code == 200
    tasks = response.json()["items"]

    # Should have 2 tasks: original (completed) and new recurring task
    assert len(tasks) == 2

    # Find the new task (not the original one)
    new_task = next((t for t in tasks if t["id"] != task.id), None)
    assert new_task is not None
    assert new_task["title"] == "Recurring Task"

    # Parse the due_date and verify the time is preserved (17:00)
    new_due_date = datetime.fromisoformat(new_task["due_date"].replace("Z", "+00:00"))
    assert new_due_date.hour == 17
    assert new_due_date.minute == 0
    assert new_due_date.second == 0


@pytest.mark.integration
async def test_fixed_recurrence_uses_original_due_date(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Test that fixed recurrence strategy calculates from the original due date."""
    from datetime import datetime, timezone
    from app.models.tenant.task import Task
    from app.services.tenant import task_statuses as task_statuses_service

    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)

    # Create statuses
    statuses = await task_statuses_service.ensure_default_statuses(
        session, a.project.id
    )
    todo_status = next(s for s in statuses if s.is_default)
    done_status = next(s for s in statuses if s.name == "Done")
    await session.commit()

    # Create a task with fixed recurrence due at 09:30
    original_due_time = datetime(2026, 1, 20, 9, 30, 0, tzinfo=timezone.utc)
    recurrence_data = {
        "frequency": "daily",
        "interval": 2,
        "ends": "never",
    }

    task = Task(
        title="Fixed Recurring Task",
        project_id=a.project.id,
        task_status_id=todo_status.id,
        guild_id=a.guild.id,
        due_date=original_due_time,
        recurrence=recurrence_data,
        recurrence_strategy="fixed",  # Fixed mode (default)
    )
    session.add(task)
    await session.commit()
    await session.refresh(task)

    # Mark the task as done
    response = await client.patch(
        a.g(f"/tasks/{task.id}"),
        headers=a.headers,
        json={"task_status_id": done_status.id},
    )

    assert response.status_code == 200

    # Fetch all tasks
    conditions = json.dumps(
        [{"field": "project_id", "op": "eq", "value": a.project.id}]
    )
    response = await client.get(
        a.g(f"/tasks/?conditions={conditions}"), headers=a.headers
    )
    assert response.status_code == 200
    tasks = response.json()["items"]

    # Find the new task
    new_task = next((t for t in tasks if t["id"] != task.id), None)
    assert new_task is not None

    # Parse the due_date
    new_due_date = datetime.fromisoformat(new_task["due_date"].replace("Z", "+00:00"))

    # For fixed recurrence, next due should be 2 days after original (Jan 22)
    assert new_due_date.day == 22
    assert new_due_date.hour == 9
    assert new_due_date.minute == 30


@pytest.mark.integration
async def test_rolling_recurrence_with_midnight_time(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Test that rolling recurrence correctly preserves midnight (00:00) time."""
    from datetime import datetime, timezone
    from app.models.tenant.task import Task
    from app.services.tenant import task_statuses as task_statuses_service

    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)

    # Create statuses
    statuses = await task_statuses_service.ensure_default_statuses(
        session, a.project.id
    )
    todo_status = next(s for s in statuses if s.is_default)
    done_status = next(s for s in statuses if s.name == "Done")
    await session.commit()

    # Create a task with rolling recurrence due at midnight (00:00)
    original_due_time = datetime(2026, 1, 20, 0, 0, 0, tzinfo=timezone.utc)
    recurrence_data = {
        "frequency": "weekly",
        "interval": 1,
        "weekdays": ["monday"],
        "ends": "never",
    }

    task = Task(
        title="Midnight Task",
        project_id=a.project.id,
        task_status_id=todo_status.id,
        guild_id=a.guild.id,
        due_date=original_due_time,
        recurrence=recurrence_data,
        recurrence_strategy="rolling",
    )
    session.add(task)
    await session.commit()
    await session.refresh(task)

    # Mark the task as done
    response = await client.patch(
        a.g(f"/tasks/{task.id}"),
        headers=a.headers,
        json={"task_status_id": done_status.id},
    )

    assert response.status_code == 200

    # Fetch all tasks
    conditions = json.dumps(
        [{"field": "project_id", "op": "eq", "value": a.project.id}]
    )
    response = await client.get(
        a.g(f"/tasks/?conditions={conditions}"), headers=a.headers
    )
    assert response.status_code == 200
    tasks = response.json()["items"]

    # Find the new task
    new_task = next((t for t in tasks if t["id"] != task.id), None)
    assert new_task is not None

    # Parse the due_date and verify midnight time is preserved
    new_due_date = datetime.fromisoformat(new_task["due_date"].replace("Z", "+00:00"))
    assert new_due_date.hour == 0
    assert new_due_date.minute == 0
    assert new_due_date.second == 0


@pytest.mark.integration
async def test_rolling_recurrence_uses_user_timezone_for_completion_date(
    session: AsyncSession,
    acting_user,
):
    """The completion-date anchor for rolling recurrence is the user's
    *local* calendar day, not the UTC day.

    Repro: a 5pm-LA task is stored as 00:00 UTC the next day. Anchoring
    a "+3 days" advance off the UTC date produced one local day too
    early — completing on Sunday May 3 (LA) gave a next due of Tuesday
    May 5 (LA) instead of Wednesday May 6 (LA).
    """
    from datetime import datetime, timezone
    from app.api.v1.tenant_endpoints.tasks import _advance_recurrence_if_needed
    from app.models.tenant.task import Task, TaskStatusCategory
    from app.services.tenant import task_statuses as task_statuses_service

    a = await acting_user(
        guild_role=GuildRole.member,
        initiative=True,
        project=True,
        email="la-user@example.com",
        timezone="America/Los_Angeles",
    )
    user = a.user
    project = a.project

    statuses = await task_statuses_service.ensure_default_statuses(session, project.id)
    todo_status = next(s for s in statuses if s.is_default)
    done_status = next(s for s in statuses if s.name == "Done")
    await session.commit()

    # Original due: 5pm Los Angeles on Sunday 2026-05-03 → 00:00 UTC
    # Monday 2026-05-04. The UTC representation has already crossed
    # midnight; this is what makes the math go wrong if anchored in UTC.
    original_due = datetime(2026, 5, 4, 0, 0, 0, tzinfo=timezone.utc)
    task = Task(
        title="Feed frogs",
        project_id=project.id,
        task_status_id=todo_status.id,
        guild_id=a.guild.id,
        due_date=original_due,
        recurrence={"frequency": "daily", "interval": 3, "ends": "never"},
        recurrence_strategy="rolling",
    )
    session.add(task)
    await session.commit()
    # Eager-load every relationship the helper touches so the
    # subsequent ``_advance_recurrence_if_needed`` call doesn't trip
    # SQLAlchemy's async-greenlet guard on a lazy load.
    await session.refresh(
        task, attribute_names=["task_status", "assignees", "tag_links"]
    )

    # Simulate the user completing the task at ~9pm Los Angeles on the
    # same Sunday (2026-05-03). In UTC that's 04:00 Monday 2026-05-04.
    completion_now = datetime(2026, 5, 4, 4, 0, 0, tzinfo=timezone.utc)
    task.task_status_id = done_status.id  # ty: ignore[invalid-assignment] — persisted row, id is set
    task.task_status = done_status

    advanced = await _advance_recurrence_if_needed(
        session,
        task,
        previous_status_category=TaskStatusCategory.todo,
        now=completion_now,
        user_timezone=user.timezone,
    )
    assert advanced is True
    await session.commit()

    from sqlmodel import select as _select

    new_task = (
        await session.exec(
            _select(Task).where(Task.project_id == project.id, Task.id != task.id)
        )
    ).first()
    assert new_task is not None
    assert new_task.due_date is not None
    # Expected: 5pm Los Angeles on Wednesday 2026-05-06 → 00:00 UTC
    # Thursday 2026-05-07 (DST: PDT is UTC-7 on this date).
    new_due_local = new_task.due_date.astimezone(ZoneInfo("America/Los_Angeles"))
    assert new_due_local.year == 2026
    assert new_due_local.month == 5
    assert new_due_local.day == 6
    assert new_due_local.hour == 17


@pytest.mark.integration
async def test_rolling_recurrence_spring_forward_preserves_wall_clock_time(
    session: AsyncSession,
    acting_user,
):
    """When the original due time would land in the clocked-forward gap
    on a spring-forward night, rolling recurrence preserves the
    original *wall-clock* time on the next calendar day rather than
    normalising into the gap. This is alarm-clock semantics: "every
    day at 2:30 AM" continues to fire at 2:30 AM after DST, even
    though 2:30 AM does not exist on the spring-forward night itself.

    Concretely: completing on 2026-03-08 (US spring-forward day) with
    an original 2:30 AM due time produces a next occurrence of
    2026-03-09 at 02:30 PDT = 09:30 UTC. The gap on Mar 8 is
    irrelevant because the new occurrence lands on Mar 9, where 2:30
    AM is a valid local time.
    """
    from datetime import datetime, timezone
    from app.api.v1.tenant_endpoints.tasks import _advance_recurrence_if_needed
    from app.models.tenant.task import Task, TaskStatusCategory
    from app.services.tenant import task_statuses as task_statuses_service

    a = await acting_user(
        guild_role=GuildRole.member,
        initiative=True,
        project=True,
        email="dst-user@example.com",
        timezone="America/Los_Angeles",
    )
    user = a.user
    project = a.project

    statuses = await task_statuses_service.ensure_default_statuses(session, project.id)
    todo_status = next(s for s in statuses if s.is_default)
    done_status = next(s for s in statuses if s.name == "Done")
    await session.commit()

    # Original due: 2:30 AM Los Angeles. On a normal day that's 09:30
    # (PST) or 10:30 (PDT) UTC; we just pick a non-DST date so the
    # field value is unambiguous in storage.
    original_due = datetime(2026, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
    task = Task(
        title="DST gap task",
        project_id=project.id,
        task_status_id=todo_status.id,
        guild_id=a.guild.id,
        due_date=original_due,
        recurrence={"frequency": "daily", "interval": 1, "ends": "never"},
        recurrence_strategy="rolling",
    )
    session.add(task)
    await session.commit()
    await session.refresh(
        task, attribute_names=["task_status", "assignees", "tag_links"]
    )

    # Complete on Sunday 2026-03-08 (US spring-forward day), late
    # morning LA so ``now_local`` is firmly in PDT. The composed
    # rolling base — ``now_local.replace(hour=2, minute=30)`` —
    # references a local time that does not exist on Mar 8 (the
    # clock jumped 2:00 → 3:00 earlier that morning). Adding one
    # day before the stored conversion lands the new occurrence on
    # Mar 9 at 02:30 PDT, which is a valid local time and matches
    # the user's "every day at 2:30 AM" intent.
    completion_now = datetime(2026, 3, 8, 18, 0, 0, tzinfo=timezone.utc)
    task.task_status_id = done_status.id  # ty: ignore[invalid-assignment] — persisted row, id is set
    task.task_status = done_status

    advanced = await _advance_recurrence_if_needed(
        session,
        task,
        previous_status_category=TaskStatusCategory.todo,
        now=completion_now,
        user_timezone=user.timezone,
    )
    assert advanced is True
    await session.commit()

    from sqlmodel import select as _select

    new_task = (
        await session.exec(
            _select(Task).where(Task.project_id == project.id, Task.id != task.id)
        )
    ).first()
    assert new_task is not None
    assert new_task.due_date is not None
    new_due_la = new_task.due_date.astimezone(ZoneInfo("America/Los_Angeles"))
    # Daily +1 from completion (Mar 8) → Mar 9, fully in PDT. The
    # important property: the wall-clock 2:30 AM of the original task
    # is preserved on the next valid day, so the user's "every day at
    # 2:30 AM" intent survives the DST transition. Strict UTC pin:
    # 2026-03-09 09:30 UTC = 2026-03-09 02:30 PDT.
    assert new_due_la.day == 9
    assert new_due_la.hour == 2
    assert new_due_la.minute == 30
    new_due_utc = new_task.due_date.astimezone(timezone.utc)
    assert new_due_utc == datetime(2026, 3, 9, 9, 30, 0, tzinfo=timezone.utc)


@pytest.mark.integration
async def test_filter_tasks_by_date_window_group(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """An OR group windows tasks by start_date OR due_date.

    The shape the calendar sends: a task belongs on screen if either of its
    dates lands in the visible range, so a task due in-window but started
    before it must still come back.
    """
    from datetime import datetime, timezone

    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)

    async def _dated(title, start, due):
        task = await _create_task(session, a.project, title)
        task.start_date = start
        task.due_date = due
        session.add(task)
        await session.commit()
        return task

    def _at(day):
        return datetime(2026, 6, day, 12, 0, tzinfo=timezone.utc)

    # Window is June 2026; each task is named for why it should/shouldn't match.
    both_inside = await _dated("both inside", _at(10), _at(11))
    due_only = await _dated("due only", None, _at(12))
    start_only = await _dated("start only", _at(13), None)
    # Starts in May, due in June: the due marker is on screen.
    straddles = await _dated(
        "straddles", datetime(2026, 5, 20, 12, 0, tzinfo=timezone.utc), _at(14)
    )
    outside = await _dated(
        "outside",
        datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc),
        datetime(2026, 8, 2, 12, 0, tzinfo=timezone.utc),
    )
    undated = await _create_task(session, a.project, "undated")

    window_start = "2026-06-01T00:00:00+00:00"
    window_end = "2026-06-30T23:59:59+00:00"
    conditions = json.dumps(
        [
            {
                "logic": "or",
                "conditions": [
                    {
                        "logic": "and",
                        "conditions": [
                            {"field": field, "op": "gte", "value": window_start},
                            {"field": field, "op": "lte", "value": window_end},
                        ],
                    }
                    for field in ("start_date", "due_date")
                ],
            }
        ]
    )

    # params= rather than an f-string URL: the "+" in a UTC offset is a space
    # once the query string is decoded.
    response = await client.get(
        a.g("/tasks/"),
        params={"conditions": conditions, "page_size": 0},
        headers=a.headers,
    )

    assert response.status_code == 200
    returned = {t["id"] for t in response.json()["items"]}
    assert returned == {both_inside.id, due_only.id, start_only.id, straddles.id}
    assert outside.id not in returned
    assert undated.id not in returned


@pytest.mark.integration
async def test_list_tasks_rejects_conditions_nested_too_deeply(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    conditions = json.dumps(
        [
            {
                "conditions": [
                    {"conditions": [{"conditions": [{"field": "id", "value": 1}]}]}
                ]
            }
        ]
    )

    response = await client.get(
        a.g(f"/tasks/?conditions={conditions}"), headers=a.headers
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "QUERY_INVALID_CONDITIONS"


@pytest.mark.integration
async def test_read_task_includes_creator_summary(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The task read embeds a ``creator`` summary so the detail view can show
    'Created by …' without fetching the whole guild roster."""
    a = await acting_user(
        guild_role=GuildRole.member, initiative=True, project=True, full_name="Ada C."
    )
    create = await client.post(
        a.g("/tasks/"),
        headers=a.headers,
        json={"title": "Authored Task", "project_id": a.project.id},
    )
    assert create.status_code == 201
    task_id = create.json()["id"]

    response = await client.get(a.g(f"/tasks/{task_id}"), headers=a.headers)
    assert response.status_code == 200
    body = response.json()
    assert body["created_by_id"] == a.user.id
    assert body["creator"] is not None
    assert body["creator"]["id"] == a.user.id
    assert body["creator"]["full_name"] == "Ada C."


@pytest.mark.integration
async def test_autocomplete_tasks_empty_query_returns_recent(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """An empty ``q`` is the picker's opening state — it lists tasks (id +
    title), not 422. Without this a typeahead shows nothing until the user
    types."""
    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    task1 = await _create_task(session, a.project, "Alpha Task")
    task2 = await _create_task(session, a.project, "Beta Task")

    response = await client.get(
        a.g("/tasks/autocomplete"),
        headers=a.headers,
        params={"q": "", "limit": 20},
    )

    assert response.status_code == 200
    items = response.json()
    # Slim projection — only id + title, none of the heavy list-row fields.
    assert all(set(item.keys()) == {"id", "title"} for item in items)
    assert {item["title"] for item in items} == {"Alpha Task", "Beta Task"}
    assert {item["id"] for item in items} == {task1.id, task2.id}


@pytest.mark.integration
async def test_autocomplete_tasks_filters_by_query(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    await _create_task(session, a.project, "Alpha Task")
    await _create_task(session, a.project, "Beta Task")

    response = await client.get(
        a.g("/tasks/autocomplete"),
        headers=a.headers,
        params={"q": "beta", "limit": 20},
    )

    assert response.status_code == 200
    assert [item["title"] for item in response.json()] == ["Beta Task"]


@pytest.mark.integration
async def test_autocomplete_tasks_escapes_like_wildcards(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """A literal ``%`` in the query matches itself, not every title."""
    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    await _create_task(session, a.project, "Plain Task")
    await _create_task(session, a.project, "50% Done")

    response = await client.get(
        a.g("/tasks/autocomplete"),
        headers=a.headers,
        params={"q": "%", "limit": 20},
    )

    assert response.status_code == 200
    assert [item["title"] for item in response.json()] == ["50% Done"]


@pytest.mark.integration
async def test_autocomplete_tasks_honors_limit(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    for i in range(5):
        await _create_task(session, a.project, f"Task {i}")

    response = await client.get(
        a.g("/tasks/autocomplete"),
        headers=a.headers,
        params={"q": "", "limit": 2},
    )

    assert response.status_code == 200
    assert len(response.json()) == 2


@pytest.mark.integration
async def test_autocomplete_tasks_accepts_command_palette_limit(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The command palette requests limit=25 — the cap must accommodate it
    (regression: a lower cap 422'd the palette's task search)."""
    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    await _create_task(session, a.project, "Task A")

    response = await client.get(
        a.g("/tasks/autocomplete"),
        headers=a.headers,
        params={"q": "", "limit": 25},
    )

    assert response.status_code == 200


@pytest.mark.integration
async def test_autocomplete_tasks_rejects_non_positive_limit(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """``limit`` is bounded at 1 — a negative value is rejected at validation
    rather than reaching Postgres (which errors on a negative LIMIT)."""
    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)

    response = await client.get(
        a.g("/tasks/autocomplete"),
        headers=a.headers,
        params={"q": "", "limit": -1},
    )

    assert response.status_code == 422


@pytest.mark.integration
async def test_autocomplete_tasks_excludes_archived(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    live = await _create_task(session, a.project, "Live Task")
    archived = await _create_task(session, a.project, "Archived Task")
    archived.is_archived = True
    session.add(archived)
    await session.commit()

    response = await client.get(
        a.g("/tasks/autocomplete"),
        headers=a.headers,
        params={"q": "", "limit": 20},
    )

    assert response.status_code == 200
    ids = {item["id"] for item in response.json()}
    assert live.id in ids
    assert archived.id not in ids


@pytest.mark.integration
async def test_autocomplete_tasks_respects_initiative_isolation(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """A guild member who isn't in the owning initiative must not see its tasks
    surface in autocomplete — RLS hides the row (the hard isolation boundary)."""
    owner = await acting_user(
        guild_role=GuildRole.member, initiative=True, project=True
    )
    outsider = await acting_user(guild_role=GuildRole.member, guild=owner.guild)
    hidden = await _create_task(session, owner.project, "Hidden Task")

    response = await client.get(
        outsider.g("/tasks/autocomplete"),
        headers=outsider.headers,
        params={"q": "", "limit": 20},
    )

    assert response.status_code == 200
    assert hidden.id not in {item["id"] for item in response.json()}


@pytest.mark.integration
async def test_autocomplete_tasks_scopes_to_initiative(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """``initiative_id`` narrows the typeahead to one initiative's tasks — the
    queue picker scopes to the initiative that owns the queue."""
    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    here = await _create_task(session, a.project, "Here Task")

    other_initiative = await create_initiative(session, a.guild, a.user)
    other_project = await create_project(session, other_initiative, a.user)
    there = await _create_task(session, other_project, "There Task")

    response = await client.get(
        a.g("/tasks/autocomplete"),
        headers=a.headers,
        params={"initiative_id": a.initiative.id, "q": "", "limit": 20},
    )

    assert response.status_code == 200
    ids = {item["id"] for item in response.json()}
    assert here.id in ids
    assert there.id not in ids
