"""Integration tests for per-assignee completion.

Completion is per assignment, not per task: you can be finished with your share
while the task itself is still in review or waiting on a co-assignee. These
cover the three rules — a task reaching done finishes every assignee's part,
leaving done erases every part, and in between a person marks their own — plus
the recategorised-column case, where a whole column crosses the done boundary
without a single task row being written.
"""

import pytest
from httpx import AsyncClient
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.guild import GuildRole
from app.models.tenant.task import TaskAssignee, TaskStatus, TaskStatusCategory
from app.services.tenant import task_statuses as task_statuses_service
from app.testing import Actor
from app.testing.factories import create_task
from app.testing.schema_harness import route_session_to_guild


async def _statuses(
    session: AsyncSession, project
) -> dict[TaskStatusCategory, TaskStatus]:
    await task_statuses_service.ensure_default_statuses(session, project.id)
    statuses = await task_statuses_service.list_statuses(session, project.id)
    await session.commit()
    return {s.category: s for s in statuses}


async def _completion(session: AsyncSession, a: Actor, task_id: int, user_id: int):
    """Read one assignment's completion straight from the guild schema."""
    await route_session_to_guild(session, a.guild.id)
    row = (
        await session.exec(
            select(TaskAssignee).where(
                TaskAssignee.task_id == task_id, TaskAssignee.user_id == user_id
            )
        )
    ).first()
    return row.completed_at if row else None


# --- marking your own part ---------------------------------------------------


@pytest.mark.integration
async def test_marking_my_part_leaves_a_shared_task_open(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The whole point: my part can be finished while the task is not."""
    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    b = await acting_user(
        guild_role=GuildRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )
    task = await create_task(
        session, a.project, title="Shared", assignees=[a.user, b.user]
    )

    response = await client.put(
        a.g(f"/tasks/{task.id}/my-part"), headers=a.headers, json={"completed": True}
    )

    assert response.status_code == 200, response.text
    assert response.json()["task_status"]["category"] != "done"
    assert await _completion(session, a, task.id, a.user.id) is not None


@pytest.mark.integration
async def test_unmarking_my_part_clears_it(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    b = await acting_user(
        guild_role=GuildRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )
    task = await create_task(
        session, a.project, title="Shared", assignees=[a.user, b.user]
    )

    await client.put(
        a.g(f"/tasks/{task.id}/my-part"), headers=a.headers, json={"completed": True}
    )
    response = await client.put(
        a.g(f"/tasks/{task.id}/my-part"), headers=a.headers, json={"completed": False}
    )

    assert response.status_code == 200, response.text
    assert await _completion(session, a, task.id, a.user.id) is None


@pytest.mark.integration
async def test_marking_twice_keeps_the_first_time(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    b = await acting_user(
        guild_role=GuildRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )
    task = await create_task(
        session, a.project, title="Shared", assignees=[a.user, b.user]
    )

    await client.put(
        a.g(f"/tasks/{task.id}/my-part"), headers=a.headers, json={"completed": True}
    )
    first = await _completion(session, a, task.id, a.user.id)
    await client.put(
        a.g(f"/tasks/{task.id}/my-part"), headers=a.headers, json={"completed": True}
    )

    assert await _completion(session, a, task.id, a.user.id) == first


@pytest.mark.integration
async def test_someone_who_is_not_assigned_has_no_part_to_finish(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    b = await acting_user(
        guild_role=GuildRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )
    task = await create_task(session, a.project, title="Draft", assignees=[a.user])

    response = await client.put(
        a.g(f"/tasks/{task.id}/my-part"), headers=b.headers, json={"completed": True}
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "TASK_NOT_ASSIGNED"


@pytest.mark.integration
async def test_one_assignee_finishing_leaves_the_others_outstanding(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    b = await acting_user(
        guild_role=GuildRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )
    task = await create_task(
        session, a.project, title="Shared", assignees=[a.user, b.user]
    )

    await client.put(
        a.g(f"/tasks/{task.id}/my-part"), headers=a.headers, json={"completed": True}
    )

    assert await _completion(session, a, task.id, a.user.id) is not None
    assert await _completion(session, a, task.id, b.user.id) is None


# --- the task crossing the done boundary ------------------------------------


@pytest.mark.integration
async def test_finishing_the_task_finishes_every_assignee(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    b = await acting_user(
        guild_role=GuildRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )
    statuses = await _statuses(session, a.project)
    task = await create_task(
        session, a.project, title="Shared", assignees=[a.user, b.user]
    )

    response = await client.patch(
        a.g(f"/tasks/{task.id}"),
        headers=a.headers,
        json={"task_status_id": statuses[TaskStatusCategory.done].id},
    )

    assert response.status_code == 200, response.text
    assert await _completion(session, a, task.id, a.user.id) is not None
    assert await _completion(session, a, task.id, b.user.id) is not None


@pytest.mark.integration
async def test_finishing_the_task_keeps_an_earlier_mark(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Someone who finished on Tuesday did not finish again on Thursday."""
    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    statuses = await _statuses(session, a.project)
    task = await create_task(session, a.project, title="Draft", assignees=[a.user])

    await client.put(
        a.g(f"/tasks/{task.id}/my-part"), headers=a.headers, json={"completed": True}
    )
    marked_at = await _completion(session, a, task.id, a.user.id)

    await client.patch(
        a.g(f"/tasks/{task.id}"),
        headers=a.headers,
        json={"task_status_id": statuses[TaskStatusCategory.done].id},
    )

    assert await _completion(session, a, task.id, a.user.id) == marked_at


@pytest.mark.integration
async def test_reopening_the_task_erases_every_part(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    b = await acting_user(
        guild_role=GuildRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )
    statuses = await _statuses(session, a.project)
    task = await create_task(
        session,
        a.project,
        title="Shared",
        assignees=[a.user, b.user],
        status_category=TaskStatusCategory.done,
    )

    response = await client.patch(
        a.g(f"/tasks/{task.id}"),
        headers=a.headers,
        json={"task_status_id": statuses[TaskStatusCategory.in_progress].id},
    )

    assert response.status_code == 200, response.text
    assert await _completion(session, a, task.id, a.user.id) is None
    assert await _completion(session, a, task.id, b.user.id) is None


@pytest.mark.integration
async def test_handing_a_task_on_keeps_my_mark(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Finish your share, then move it to review: the mark survives, because
    only the done boundary disturbs it."""
    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    b = await acting_user(
        guild_role=GuildRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )
    statuses = await _statuses(session, a.project)
    task = await create_task(
        session, a.project, title="Shared", assignees=[a.user, b.user]
    )

    await client.put(
        a.g(f"/tasks/{task.id}/my-part"), headers=a.headers, json={"completed": True}
    )
    await client.patch(
        a.g(f"/tasks/{task.id}"),
        headers=a.headers,
        json={"task_status_id": statuses[TaskStatusCategory.todo].id},
    )

    assert await _completion(session, a, task.id, a.user.id) is not None


# --- recategorising a whole column ------------------------------------------


@pytest.mark.integration
async def test_recategorising_a_column_into_done_finishes_its_assignments(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    statuses = await _statuses(session, a.project)
    todo_status = statuses[TaskStatusCategory.todo]
    task = await create_task(
        session,
        a.project,
        title="Draft",
        assignees=[a.user],
        task_status_id=todo_status.id,
    )

    response = await client.patch(
        a.g(f"/projects/{a.project.id}/task-statuses/{todo_status.id}"),
        headers=a.headers,
        json={"category": "done"},
    )

    assert response.status_code == 200, response.text
    assert await _completion(session, a, task.id, a.user.id) is not None


@pytest.mark.integration
async def test_recategorising_a_column_out_of_done_erases_its_assignments(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    statuses = await _statuses(session, a.project)
    done_status = statuses[TaskStatusCategory.done]
    keeper = await client.post(
        a.g(f"/projects/{a.project.id}/task-statuses/"),
        headers=a.headers,
        json={"name": "Shipped", "category": "done"},
    )
    assert keeper.status_code == 201, keeper.text

    task = await create_task(
        session,
        a.project,
        title="Draft",
        assignees=[a.user],
        status_category=TaskStatusCategory.done,
        task_status_id=done_status.id,
    )
    assert await _completion(session, a, task.id, a.user.id) is not None

    response = await client.patch(
        a.g(f"/projects/{a.project.id}/task-statuses/{done_status.id}"),
        headers=a.headers,
        json={"category": "in_progress"},
    )

    assert response.status_code == 200, response.text
    assert await _completion(session, a, task.id, a.user.id) is None


# --- the sole assignee ------------------------------------------------------


@pytest.mark.integration
async def test_the_only_assignee_finishing_finishes_the_task(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """With nobody else on it, your part is the whole task."""
    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    await _statuses(session, a.project)
    task = await create_task(session, a.project, title="Solo", assignees=[a.user])

    response = await client.put(
        a.g(f"/tasks/{task.id}/my-part"), headers=a.headers, json={"completed": True}
    )

    assert response.status_code == 200, response.text
    assert response.json()["task_status"]["category"] == "done"


@pytest.mark.integration
async def test_the_only_assignee_unfinishing_reopens_the_task(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Symmetric, so unchecking can never leave a done task with an
    unfinished part."""
    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    await _statuses(session, a.project)
    task = await create_task(session, a.project, title="Solo", assignees=[a.user])

    await client.put(
        a.g(f"/tasks/{task.id}/my-part"), headers=a.headers, json={"completed": True}
    )
    response = await client.put(
        a.g(f"/tasks/{task.id}/my-part"), headers=a.headers, json={"completed": False}
    )

    assert response.status_code == 200, response.text
    assert response.json()["task_status"]["category"] != "done"
    assert await _completion(session, a, task.id, a.user.id) is None
