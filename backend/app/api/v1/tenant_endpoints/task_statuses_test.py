"""
Integration tests for task status endpoints.

Covers the color/icon fields added for customizable status appearance,
including category-driven defaults and PATCH behavior around category changes.
"""

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.guild import GuildRole
from app.models.tenant.task import TaskStatusCategory
from app.services.tenant import task_statuses as task_statuses_service
from app.testing.factories import (
    create_guild,
    create_guild_membership,
    create_initiative,
    create_project,
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
    assert body["color"] == "#FBBF24"
    assert body["icon"] == "circle-pause"


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
    backlog = next(s for s in statuses if s.category == TaskStatusCategory.backlog)

    response = await client.patch(
        f"/api/v1/g/{project.guild_id}/projects/{project.id}/task-statuses/{backlog.id}",
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
        f"/api/v1/g/{project.guild_id}/projects/{project.id}/task-statuses/{blocked.id}",
        json={"color": "#ABCDEF", "icon": "flag"},
        headers=headers,
    )
    assert first.status_code == 200

    # Now change category only — color/icon should remain untouched
    second = await client.patch(
        f"/api/v1/g/{project.guild_id}/projects/{project.id}/task-statuses/{blocked.id}",
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

    assert by_category[TaskStatusCategory.backlog].color == "#94A3B8"
    assert by_category[TaskStatusCategory.backlog].icon == "circle-dashed"
    assert by_category[TaskStatusCategory.in_progress].color == "#60A5FA"
    assert by_category[TaskStatusCategory.in_progress].icon == "circle-play"
    assert by_category[TaskStatusCategory.todo].color == "#FBBF24"
    assert by_category[TaskStatusCategory.todo].icon == "circle-pause"
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
        session, a.initiative, a.user, name="Archived", is_archived=True
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
