"""
Integration tests for task status endpoints.

Covers the color/icon fields added for customizable status appearance,
including category-driven defaults and PATCH behavior around category changes.
"""

from datetime import datetime, timezone
import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from sqlmodel import select

from app.models.platform.guild import GuildRole
from app.models.tenant.initiative import InitiativeMember, InitiativeRoleModel
from app.models.tenant.task import Task, TaskStatusCategory
from app.services.tenant import task_statuses as task_statuses_service
from app.testing import route_session_to_guild
from app.testing.factories import (
    create_guild,
    create_guild_membership,
    create_initiative,
    create_project,
    create_task,
    create_task_status,
    create_user,
    get_auth_headers,
)


async def _setup_project(session: AsyncSession):
    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    await create_guild_membership(session, user=user, guild=guild)
    initiative = await create_initiative(session, guild, user, name="Test Initiative")
    project = await create_project(session, initiative, user, name="Test Project")
    headers = get_auth_headers(user)
    return project, headers


@pytest.mark.integration
async def test_create_status_uses_category_defaults(
    client: AsyncClient, session: AsyncSession
):
    project, headers = await _setup_project(session)

    response = await client.post(
        f"/api/v1/g/{project.guild_id}/projects/{project.id}/task-statuses/",
        json={"name": "Review", "category": "todo"},
        headers=headers,
    )

    assert response.status_code == 201
    body = response.json()
    assert body["color"] == "#94A3B8"
    assert body["icon"] == "circle"


@pytest.mark.integration
async def test_create_status_respects_explicit_color_icon(
    client: AsyncClient, session: AsyncSession
):
    project, headers = await _setup_project(session)

    response = await client.post(
        f"/api/v1/g/{project.guild_id}/projects/{project.id}/task-statuses/",
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
async def test_patch_updates_color_and_icon(client: AsyncClient, session: AsyncSession):
    project, headers = await _setup_project(session)
    statuses = await task_statuses_service.ensure_default_statuses(session, project.id)
    await session.commit()
    todo = next(s for s in statuses if s.category == TaskStatusCategory.todo)

    response = await client.patch(
        f"/api/v1/g/{project.guild_id}/projects/{project.id}/task-statuses/{todo.id}",
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
    todo = next(
        s
        for s in statuses
        if s.category == TaskStatusCategory.todo and s.name == "To Do"
    )

    # First set explicit custom color/icon
    first = await client.patch(
        f"/api/v1/g/{project.guild_id}/projects/{project.id}/task-statuses/{todo.id}",
        json={"color": "#ABCDEF", "icon": "flag"},
        headers=headers,
    )
    assert first.status_code == 200

    # Now change category only — color/icon should remain untouched
    second = await client.patch(
        f"/api/v1/g/{project.guild_id}/projects/{project.id}/task-statuses/{todo.id}",
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
        f"/api/v1/g/{project.guild_id}/projects/{project.id}/task-statuses/",
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

    assert [(s.name, s.category, s.is_default) for s in statuses] == [
        ("To Do", TaskStatusCategory.todo, True),
        ("In Progress", TaskStatusCategory.in_progress, False),
        ("Done", TaskStatusCategory.done, False),
    ]
    assert by_category[TaskStatusCategory.todo].color == "#94A3B8"
    assert by_category[TaskStatusCategory.todo].icon == "circle"
    assert task_statuses_service.defaults_for_category(TaskStatusCategory.backlog) == (
        "#94A3B8",
        "circle-dashed",
    )
    assert by_category[TaskStatusCategory.in_progress].color == "#60A5FA"
    assert by_category[TaskStatusCategory.in_progress].icon == "circle-play"
    assert by_category[TaskStatusCategory.done].color == "#34D399"
    assert by_category[TaskStatusCategory.done].icon == "circle-check"


# ---------------------------------------------------------------------------
# GET /initiatives/{initiative_id}/task-statuses/ — the columns an initiative
# offers, aggregated over the projects the caller can read.
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_initiative_statuses_collapse_across_projects(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    second = await create_project(session, a.initiative, a.user, name="Second")
    for project in (a.project, second):
        await create_task_status(
            session,
            project,
            name="Backlog",
            category=TaskStatusCategory.backlog,
            position=0,
        )
    await create_task_status(
        session,
        a.project,
        name="Blocked",
        category=TaskStatusCategory.todo,
        position=1,
        color="#FBBF24",
        icon="circle-pause",
    )

    response = await client.get(
        a.g(f"/initiatives/{a.initiative.id}/task-statuses/"), headers=a.headers
    )

    assert response.status_code == 200
    body = response.json()
    # Ordered by board position: the shared Backlog column, then Blocked.
    assert body == [
        {
            "name": "Backlog",
            "category": "backlog",
            "color": "#94A3B8",
            "icon": "circle-dashed",
            "project_count": 2,
            "projects_total": 2,
        },
        {
            "name": "Blocked",
            "category": "todo",
            "color": "#FBBF24",
            "icon": "circle-pause",
            "project_count": 1,
            "projects_total": 2,
        },
    ]


@pytest.mark.integration
async def test_initiative_statuses_separate_same_name_by_category(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    await create_task_status(
        session, a.project, name="Review", category=TaskStatusCategory.todo, position=0
    )
    await create_task_status(
        session,
        a.project,
        name="Review",
        category=TaskStatusCategory.done,
        position=1,
    )

    response = await client.get(
        a.g(f"/initiatives/{a.initiative.id}/task-statuses/"), headers=a.headers
    )

    assert response.status_code == 200
    body = response.json()
    assert [(entry["name"], entry["category"]) for entry in body] == [
        ("Review", "todo"),
        ("Review", "done"),
    ]


@pytest.mark.integration
async def test_initiative_statuses_only_cover_readable_projects(
    client: AsyncClient, session: AsyncSession, acting_user
):
    owner = await acting_user(
        guild_role=GuildRole.member, initiative=True, project=True
    )
    await create_task_status(
        session, owner.project, name="Unshared", category=TaskStatusCategory.todo
    )
    member = await acting_user(
        guild_role=GuildRole.member,
        guild=owner.guild,
        initiative=owner.initiative,
        initiative_role="member",
    )
    theirs = await create_project(session, owner.initiative, member.user, name="Theirs")
    await create_task_status(
        session, theirs, name="Shared", category=TaskStatusCategory.todo
    )

    response = await client.get(
        member.g(f"/initiatives/{owner.initiative.id}/task-statuses/"),
        headers=member.headers,
    )

    assert response.status_code == 200
    body = response.json()
    # The project they hold no grant on contributes neither a column nor a
    # project to the total.
    assert [entry["name"] for entry in body] == ["Shared"]
    assert body[0]["projects_total"] == 1


@pytest.mark.integration
async def test_initiative_statuses_skip_archived_and_template_projects(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    await create_task_status(
        session, a.project, name="Active", category=TaskStatusCategory.todo
    )
    archived = await create_project(
        session,
        a.initiative,
        a.user,
        name="Archived",
        archived_at=datetime.now(timezone.utc),
    )
    await create_task_status(
        session, archived, name="Archived Only", category=TaskStatusCategory.todo
    )
    template = await create_project(
        session, a.initiative, a.user, name="Template", is_template=True
    )
    await create_task_status(
        session, template, name="Template Only", category=TaskStatusCategory.todo
    )

    response = await client.get(
        a.g(f"/initiatives/{a.initiative.id}/task-statuses/"), headers=a.headers
    )

    assert response.status_code == 200
    body = response.json()
    assert [entry["name"] for entry in body] == ["Active"]
    assert body[0]["projects_total"] == 1


@pytest.mark.integration
async def test_initiative_statuses_empty_when_no_readable_projects(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(guild_role=GuildRole.member, initiative=True)

    response = await client.get(
        a.g(f"/initiatives/{a.initiative.id}/task-statuses/"), headers=a.headers
    )

    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.integration
async def test_initiative_statuses_cover_the_guild_for_an_admin(
    client: AsyncClient, session: AsyncSession, acting_user
):
    owner = await acting_user(
        guild_role=GuildRole.member, initiative=True, project=True
    )
    await create_task_status(
        session, owner.project, name="Unshared", category=TaskStatusCategory.todo
    )
    admin = await acting_user(guild_role=GuildRole.admin, guild=owner.guild)

    response = await client.get(
        admin.g(f"/initiatives/{owner.initiative.id}/task-statuses/"),
        headers=admin.headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert [entry["name"] for entry in body] == ["Unshared"]
    assert body[0]["projects_total"] == 1


async def _grant_full_access(session: AsyncSession, initiative, user) -> None:
    """Turn on "Full access" for the role ``user`` holds in ``initiative``."""
    await route_session_to_guild(session, initiative.guild_id)
    membership = (
        await session.exec(
            select(InitiativeMember).where(
                InitiativeMember.initiative_id == initiative.id,
                InitiativeMember.user_id == user.id,
            )
        )
    ).one()
    role = await session.get(InitiativeRoleModel, membership.role_id)
    assert role is not None
    role.override_share_restrictions = True
    session.add(role)
    await session.commit()


@pytest.mark.integration
async def test_initiative_statuses_cover_the_initiative_on_full_access(
    client: AsyncClient, session: AsyncSession, acting_user
):
    owner = await acting_user(
        guild_role=GuildRole.member, initiative=True, project=True
    )
    await create_task_status(
        session, owner.project, name="Unshared", category=TaskStatusCategory.todo
    )
    manager = await acting_user(
        guild_role=GuildRole.member,
        guild=owner.guild,
        initiative=owner.initiative,
        initiative_role="project_manager",
    )
    await _grant_full_access(session, owner.initiative, manager.user)

    response = await client.get(
        manager.g(f"/initiatives/{owner.initiative.id}/task-statuses/"),
        headers=manager.headers,
    )

    # Full access reaches every project in the initiative, so the column shows
    # up here exactly as it would when opening that project directly.
    assert response.status_code == 200
    body = response.json()
    assert [entry["name"] for entry in body] == ["Unshared"]
    assert body[0]["project_count"] == 1
    assert body[0]["projects_total"] == 1


@pytest.mark.integration
async def test_initiative_statuses_refused_to_a_non_member(
    client: AsyncClient, session: AsyncSession, acting_user
):
    owner = await acting_user(
        guild_role=GuildRole.member, initiative=True, project=True
    )
    await create_task_status(
        session, owner.project, name="Unshared", category=TaskStatusCategory.todo
    )
    outsider = await acting_user(guild_role=GuildRole.member, guild=owner.guild)

    response = await client.get(
        outsider.g(f"/initiatives/{owner.initiative.id}/task-statuses/"),
        headers=outsider.headers,
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "INITIATIVE_NOT_A_MEMBER"


@pytest.mark.integration
async def test_initiative_statuses_404_for_an_unknown_initiative(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)

    response = await client.get(
        a.g("/initiatives/999999/task-statuses/"), headers=a.headers
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "INITIATIVE_NOT_FOUND"


# ---------------------------------------------------------------------------
# DELETE /projects/{project_id}/task-statuses/{status_id} — a column can be
# retired without another column in its own category to catch its tasks.
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_delete_moves_tasks_to_the_default_without_a_fallback(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The case a legacy Blocked column was stuck in: no todo sibling to name."""
    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    statuses = await task_statuses_service.ensure_default_statuses(
        session, a.project.id
    )
    await session.commit()
    default_status = next(s for s in statuses if s.is_default)
    blocked = await create_task_status(
        session, a.project, name="Blocked", category=TaskStatusCategory.todo, position=9
    )
    created = await client.post(
        a.g("/tasks/"),
        headers=a.headers,
        json={
            "project_id": a.project.id,
            "title": "Waiting on legal",
            "task_status_id": blocked.id,
        },
    )
    assert created.status_code == 201, created.text

    response = await client.request(
        "DELETE",
        a.g(f"/projects/{a.project.id}/task-statuses/{blocked.id}"),
        headers=a.headers,
        json={},
    )

    assert response.status_code == 204, response.text
    task = await client.get(a.g(f"/tasks/{created.json()['id']}"), headers=a.headers)
    assert task.json()["task_status_id"] == default_status.id


@pytest.mark.integration
async def test_delete_accepts_a_fallback_in_another_category(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    statuses = await task_statuses_service.ensure_default_statuses(
        session, a.project.id
    )
    await session.commit()
    in_progress = next(
        s for s in statuses if s.category == TaskStatusCategory.in_progress
    )
    blocked = await create_task_status(
        session, a.project, name="Blocked", category=TaskStatusCategory.todo, position=9
    )
    created = await client.post(
        a.g("/tasks/"),
        headers=a.headers,
        json={
            "project_id": a.project.id,
            "title": "Unblocked",
            "task_status_id": blocked.id,
        },
    )
    assert created.status_code == 201, created.text

    response = await client.request(
        "DELETE",
        a.g(f"/projects/{a.project.id}/task-statuses/{blocked.id}"),
        headers=a.headers,
        json={"fallback_status_id": in_progress.id},
    )

    assert response.status_code == 204, response.text
    task = await client.get(a.g(f"/tasks/{created.json()['id']}"), headers=a.headers)
    assert task.json()["task_status_id"] == in_progress.id


@pytest.mark.integration
async def test_delete_into_done_completes_the_tasks_it_moves(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Crossing the done boundary stamps ``completed_at``, as a task move would."""
    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    statuses = await task_statuses_service.ensure_default_statuses(
        session, a.project.id
    )
    await session.commit()
    todo = next(s for s in statuses if s.category == TaskStatusCategory.todo)
    done = next(s for s in statuses if s.category == TaskStatusCategory.done)
    created = await client.post(
        a.g("/tasks/"),
        headers=a.headers,
        json={
            "project_id": a.project.id,
            "title": "Shipped after all",
            "task_status_id": todo.id,
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["completed_at"] is None

    response = await client.request(
        "DELETE",
        a.g(f"/projects/{a.project.id}/task-statuses/{todo.id}"),
        headers=a.headers,
        json={"fallback_status_id": done.id},
    )

    assert response.status_code == 204, response.text
    task = await client.get(a.g(f"/tasks/{created.json()['id']}"), headers=a.headers)
    assert task.json()["completed_at"] is not None


@pytest.mark.integration
async def test_delete_into_done_advances_a_recurring_task(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    statuses = await task_statuses_service.ensure_default_statuses(
        session, a.project.id
    )
    default_status = next(status for status in statuses if status.is_default)
    remaining_statuses = [
        status for status in statuses if status.id != default_status.id
    ]
    successor_status = (
        task_statuses_service.first_by_category_preference(remaining_statuses)
        or remaining_statuses[0]
    )
    done = next(
        status for status in statuses if status.category == TaskStatusCategory.done
    )
    due = datetime(2026, 9, 16, 12, 0, tzinfo=timezone.utc)
    recurring = await create_task(
        session,
        a.project,
        title="Daily check",
        task_status_id=default_status.id,
        due_date=due,
        recurrence={"frequency": "daily", "interval": 1, "ends": "never"},
        recurrence_strategy="fixed",
    )

    response = await client.request(
        "DELETE",
        a.g(f"/projects/{a.project.id}/task-statuses/{default_status.id}"),
        headers=a.headers,
        json={"fallback_status_id": done.id},
    )

    assert response.status_code == 204, response.text
    session.expunge_all()
    tasks = list(
        await session.exec(
            select(Task).where(
                Task.project_id == a.project.id,
                Task.title == "Daily check",
            )
        )
    )
    assert len(tasks) == 2
    completed = next(task for task in tasks if task.id == recurring.id)
    successor = next(task for task in tasks if task.id != recurring.id)
    assert completed.completed_at is not None
    assert completed.recurrence is None
    assert successor.task_status_id == successor_status.id
    assert successor.due_date == datetime(2026, 9, 17, 12, 0, tzinfo=timezone.utc)
    assert successor.recurrence is not None
    assert successor.recurrence["frequency"] == "daily"
    assert successor.recurrence["interval"] == 1
    assert successor.recurrence["ends"] == "never"


@pytest.mark.integration
async def test_delete_can_remove_the_last_status_of_a_category(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    statuses = await task_statuses_service.ensure_default_statuses(
        session, a.project.id
    )
    await session.commit()
    done = next(s for s in statuses if s.category == TaskStatusCategory.done)

    response = await client.request(
        "DELETE",
        a.g(f"/projects/{a.project.id}/task-statuses/{done.id}"),
        headers=a.headers,
        json={},
    )

    assert response.status_code == 204, response.text
    remaining = await client.get(
        a.g(f"/projects/{a.project.id}/task-statuses/"), headers=a.headers
    )
    assert [s["category"] for s in remaining.json()] == ["todo", "in_progress"]


@pytest.mark.integration
async def test_delete_refuses_the_projects_only_status(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    only = await create_task_status(
        session, a.project, name="Everything", category=TaskStatusCategory.todo
    )

    response = await client.request(
        "DELETE",
        a.g(f"/projects/{a.project.id}/task-statuses/{only.id}"),
        headers=a.headers,
        json={},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "TASK_STATUS_CANNOT_REMOVE_LAST"


@pytest.mark.integration
async def test_deleting_the_default_promotes_the_next_entry_column(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    statuses = await task_statuses_service.ensure_default_statuses(
        session, a.project.id
    )
    await session.commit()
    todo = next(s for s in statuses if s.category == TaskStatusCategory.todo)
    await create_task_status(
        session,
        a.project,
        name="Someday",
        category=TaskStatusCategory.backlog,
        position=9,
    )

    response = await client.request(
        "DELETE",
        a.g(f"/projects/{a.project.id}/task-statuses/{todo.id}"),
        headers=a.headers,
        json={},
    )

    assert response.status_code == 204, response.text
    remaining = await client.get(
        a.g(f"/projects/{a.project.id}/task-statuses/"), headers=a.headers
    )
    default = next(s for s in remaining.json() if s["is_default"])
    assert default["name"] == "Someday"


@pytest.mark.integration
async def test_a_legacy_projects_entry_column_is_its_backlog_not_its_blocked(
    session: AsyncSession, acting_user
):
    """A project seeded before this change keeps Backlog as where work starts.

    Its Blocked column is ``todo``, so a preference that reached for ``todo``
    first would start every task in it.
    """
    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    for name, category, position in (
        ("Backlog", TaskStatusCategory.backlog, 0),
        ("In Progress", TaskStatusCategory.in_progress, 1),
        ("Blocked", TaskStatusCategory.todo, 2),
        ("Done", TaskStatusCategory.done, 3),
    ):
        await create_task_status(
            session, a.project, name=name, category=category, position=position
        )

    statuses = await task_statuses_service.list_statuses(session, a.project.id)
    assert all(not s.is_default for s in statuses)

    entry = task_statuses_service.first_by_category_preference(statuses)
    assert entry is not None and entry.name == "Backlog"

    default_status = await task_statuses_service.get_default_status(
        session, a.project.id
    )
    assert default_status.name == "Backlog"
