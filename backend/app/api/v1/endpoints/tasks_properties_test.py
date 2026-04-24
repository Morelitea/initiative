"""
Integration tests for task custom-property endpoints.

Mirrors documents_properties_test.py for the task side:
- PUT /tasks/{id}/properties replace-all semantics
- Type validation per property type (representative set)
- user_reference non-initiative-member rejection
- Filtering via the ``conditions`` query param's ``property_values`` field
- RLS cross-initiative isolation
- Move across initiatives drops property values; duplicate in same project carries
"""

import json

import pytest
from httpx import AsyncClient
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.guild import GuildRole
from app.models.property import (
    PropertyType,
    TaskPropertyValue,
)
from app.services import task_statuses as task_statuses_service
from app.testing import (
    create_guild,
    create_guild_membership,
    create_initiative,
    create_project,
    create_property_definition,
    create_user,
    get_guild_headers,
)


async def _create_task(session: AsyncSession, project, title: str = "Task"):
    from app.models.task import Task

    await task_statuses_service.ensure_default_statuses(session, project.id)
    default_status = await task_statuses_service.get_default_status(session, project.id)

    task = Task(
        title=title,
        project_id=project.id,
        task_status_id=default_status.id,
        guild_id=project.guild_id,
    )
    session.add(task)
    await session.commit()
    await session.refresh(task)
    return task


# ---------------------------------------------------------------------------
# PUT replace-all
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_put_task_properties_sets_values(
    client: AsyncClient, session: AsyncSession
):
    user = await create_user(session, email="u@example.com")
    guild = await create_guild(session)
    await create_guild_membership(session, user=user, guild=guild, role=GuildRole.admin)
    initiative = await create_initiative(session, guild, user, name="Init")
    project = await create_project(session, initiative, user, name="P")
    task = await _create_task(session, project)

    text_defn = await create_property_definition(
        session, initiative, name="Note", type=PropertyType.text
    )
    number_defn = await create_property_definition(
        session, initiative, name="Score", type=PropertyType.number
    )

    headers = get_guild_headers(guild, user)
    response = await client.put(
        f"/api/v1/tasks/{task.id}/properties",
        headers=headers,
        json={
            "values": [
                {"property_id": text_defn.id, "value": "alpha"},
                {"property_id": number_defn.id, "value": 7.5},
            ]
        },
    )

    assert response.status_code == 200
    props = {p["property_id"]: p for p in response.json()["properties"]}
    assert props[text_defn.id]["value"] == "alpha"
    assert float(props[number_defn.id]["value"]) == 7.5


@pytest.mark.integration
async def test_put_task_properties_empty_clears_existing(
    client: AsyncClient, session: AsyncSession
):
    user = await create_user(session, email="u@example.com")
    guild = await create_guild(session)
    await create_guild_membership(session, user=user, guild=guild, role=GuildRole.admin)
    initiative = await create_initiative(session, guild, user, name="Init")
    project = await create_project(session, initiative, user, name="P")
    task = await _create_task(session, project)

    defn = await create_property_definition(
        session, initiative, name="Tag", type=PropertyType.text
    )

    headers = get_guild_headers(guild, user)
    await client.put(
        f"/api/v1/tasks/{task.id}/properties",
        headers=headers,
        json={"values": [{"property_id": defn.id, "value": "seed"}]},
    )
    response = await client.put(
        f"/api/v1/tasks/{task.id}/properties",
        headers=headers,
        json={"values": []},
    )

    assert response.status_code == 200
    assert response.json()["properties"] == []
    rows = await session.exec(
        select(TaskPropertyValue).where(TaskPropertyValue.task_id == task.id)
    )
    assert rows.all() == []


# ---------------------------------------------------------------------------
# Type validation — representative sample (text, number, date, multi_select)
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_put_task_text_rejects_non_string(
    client: AsyncClient, session: AsyncSession
):
    user = await create_user(session, email="u@example.com")
    guild = await create_guild(session)
    await create_guild_membership(session, user=user, guild=guild, role=GuildRole.admin)
    initiative = await create_initiative(session, guild, user, name="Init")
    project = await create_project(session, initiative, user, name="P")
    task = await _create_task(session, project)

    defn = await create_property_definition(
        session, initiative, name="T", type=PropertyType.text
    )

    response = await client.put(
        f"/api/v1/tasks/{task.id}/properties",
        headers=get_guild_headers(guild, user),
        json={"values": [{"property_id": defn.id, "value": 12345}]},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "PROPERTY_INVALID_VALUE_FOR_TYPE"


@pytest.mark.integration
async def test_put_task_number_accepts_numeric_string(
    client: AsyncClient, session: AsyncSession
):
    user = await create_user(session, email="u@example.com")
    guild = await create_guild(session)
    await create_guild_membership(session, user=user, guild=guild, role=GuildRole.admin)
    initiative = await create_initiative(session, guild, user, name="Init")
    project = await create_project(session, initiative, user, name="P")
    task = await _create_task(session, project)

    defn = await create_property_definition(
        session, initiative, name="N", type=PropertyType.number
    )

    response = await client.put(
        f"/api/v1/tasks/{task.id}/properties",
        headers=get_guild_headers(guild, user),
        json={"values": [{"property_id": defn.id, "value": "3.14"}]},
    )
    assert response.status_code == 200
    props = {p["property_id"]: p["value"] for p in response.json()["properties"]}
    assert float(props[defn.id]) == 3.14


@pytest.mark.integration
async def test_put_task_date_accepts_iso_and_rejects_garbage(
    client: AsyncClient, session: AsyncSession
):
    user = await create_user(session, email="u@example.com")
    guild = await create_guild(session)
    await create_guild_membership(session, user=user, guild=guild, role=GuildRole.admin)
    initiative = await create_initiative(session, guild, user, name="Init")
    project = await create_project(session, initiative, user, name="P")
    task = await _create_task(session, project)

    defn = await create_property_definition(
        session, initiative, name="D", type=PropertyType.date
    )
    headers = get_guild_headers(guild, user)

    ok = await client.put(
        f"/api/v1/tasks/{task.id}/properties",
        headers=headers,
        json={"values": [{"property_id": defn.id, "value": "2026-04-22"}]},
    )
    assert ok.status_code == 200

    bad = await client.put(
        f"/api/v1/tasks/{task.id}/properties",
        headers=headers,
        json={"values": [{"property_id": defn.id, "value": "not-a-date"}]},
    )
    assert bad.status_code == 400
    assert bad.json()["detail"] == "PROPERTY_INVALID_VALUE_FOR_TYPE"


@pytest.mark.integration
async def test_put_task_multi_select_unknown_slug_rejected(
    client: AsyncClient, session: AsyncSession
):
    user = await create_user(session, email="u@example.com")
    guild = await create_guild(session)
    await create_guild_membership(session, user=user, guild=guild, role=GuildRole.admin)
    initiative = await create_initiative(session, guild, user, name="Init")
    project = await create_project(session, initiative, user, name="P")
    task = await _create_task(session, project)

    defn = await create_property_definition(
        session, initiative, name="M", type=PropertyType.multi_select,
        options=[{"value": "a", "label": "A"}, {"value": "b", "label": "B"}],
    )

    response = await client.put(
        f"/api/v1/tasks/{task.id}/properties",
        headers=get_guild_headers(guild, user),
        json={"values": [{"property_id": defn.id, "value": ["a", "ghost"]}]},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "PROPERTY_OPTION_NOT_IN_DEFINITION"


@pytest.mark.integration
async def test_put_task_user_reference_non_initiative_member_rejected(
    client: AsyncClient, session: AsyncSession
):
    user = await create_user(session, email="u@example.com")
    outsider = await create_user(session, email="outsider@example.com")
    guild = await create_guild(session)
    await create_guild_membership(session, user=user, guild=guild, role=GuildRole.admin)
    # outsider is a guild member but NOT an initiative member
    await create_guild_membership(
        session, user=outsider, guild=guild, role=GuildRole.member
    )

    initiative = await create_initiative(session, guild, user, name="Init")
    project = await create_project(session, initiative, user, name="P")
    task = await _create_task(session, project)

    defn = await create_property_definition(
        session, initiative, name="Owner", type=PropertyType.user_reference
    )

    response = await client.put(
        f"/api/v1/tasks/{task.id}/properties",
        headers=get_guild_headers(guild, user),
        json={"values": [{"property_id": defn.id, "value": outsider.id}]},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "PROPERTY_USER_NOT_IN_INITIATIVE"


# ---------------------------------------------------------------------------
# RLS cross-guild / cross-initiative isolation
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_put_task_properties_cross_guild_task_returns_404(
    client: AsyncClient, session: AsyncSession
):
    user = await create_user(session, email="u@example.com")
    guild_a = await create_guild(session, name="A")
    guild_b = await create_guild(session, name="B")
    await create_guild_membership(session, user=user, guild=guild_a, role=GuildRole.admin)
    await create_guild_membership(session, user=user, guild=guild_b, role=GuildRole.admin)

    initiative_b = await create_initiative(session, guild_b, user, name="Init B")
    project_b = await create_project(session, initiative_b, user, name="P")
    task_b = await _create_task(session, project_b)

    # Send with guild A header — task belongs to guild B.
    response = await client.put(
        f"/api/v1/tasks/{task_b.id}/properties",
        headers=get_guild_headers(guild_a, user),
        json={"values": []},
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "TASK_NOT_FOUND"


@pytest.mark.integration
async def test_put_task_cross_initiative_definition_rejected(
    client: AsyncClient, session: AsyncSession
):
    """A definition from initiative B can't be attached to a task in A."""
    user = await create_user(session, email="u@example.com")
    guild = await create_guild(session)
    await create_guild_membership(session, user=user, guild=guild, role=GuildRole.admin)

    init_a = await create_initiative(session, guild, user, name="A")
    init_b = await create_initiative(session, guild, user, name="B")
    project_a = await create_project(session, init_a, user, name="P")
    task_a = await _create_task(session, project_a)

    defn_b = await create_property_definition(session, init_b, name="Foreign")

    response = await client.put(
        f"/api/v1/tasks/{task_a.id}/properties",
        headers=get_guild_headers(guild, user),
        json={"values": [{"property_id": defn_b.id, "value": "x"}]},
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "PROPERTY_DEFINITION_NOT_FOUND"


# ---------------------------------------------------------------------------
# Move / duplicate value cascades
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_move_task_across_initiatives_drops_property_values(
    client: AsyncClient, session: AsyncSession
):
    """Moving a task to a project in a different initiative drops its values."""
    user = await create_user(session, email="u@example.com")
    guild = await create_guild(session)
    await create_guild_membership(session, user=user, guild=guild, role=GuildRole.admin)

    init_a = await create_initiative(session, guild, user, name="A")
    init_b = await create_initiative(session, guild, user, name="B")
    project_a = await create_project(session, init_a, user, name="PA")
    project_b = await create_project(session, init_b, user, name="PB")

    task = await _create_task(session, project_a, title="Mover")
    defn = await create_property_definition(
        session, init_a, name="Tag", type=PropertyType.text
    )

    headers = get_guild_headers(guild, user)
    await client.put(
        f"/api/v1/tasks/{task.id}/properties",
        headers=headers,
        json={"values": [{"property_id": defn.id, "value": "beforeMove"}]},
    )

    move_resp = await client.post(
        f"/api/v1/tasks/{task.id}/move",
        headers=headers,
        json={"target_project_id": project_b.id},
    )
    assert move_resp.status_code == 200

    # Property values should be gone.
    rows = await session.exec(
        select(TaskPropertyValue).where(TaskPropertyValue.task_id == task.id)
    )
    assert rows.all() == []


@pytest.mark.integration
async def test_duplicate_task_same_project_carries_property_values(
    client: AsyncClient, session: AsyncSession
):
    """Duplicating a task in its own project (same initiative) copies values."""
    user = await create_user(session, email="u@example.com")
    guild = await create_guild(session)
    await create_guild_membership(session, user=user, guild=guild, role=GuildRole.admin)
    initiative = await create_initiative(session, guild, user, name="Init")
    project = await create_project(session, initiative, user, name="P")
    task = await _create_task(session, project, title="Orig")

    defn = await create_property_definition(
        session, initiative, name="Tag", type=PropertyType.text
    )

    headers = get_guild_headers(guild, user)
    await client.put(
        f"/api/v1/tasks/{task.id}/properties",
        headers=headers,
        json={"values": [{"property_id": defn.id, "value": "carry"}]},
    )

    dup_resp = await client.post(
        f"/api/v1/tasks/{task.id}/duplicate", headers=headers
    )
    assert dup_resp.status_code == 201
    dup = dup_resp.json()
    props = {p["property_id"]: p["value"] for p in dup["properties"]}
    assert props.get(defn.id) == "carry"

    dup_rows = await session.exec(
        select(TaskPropertyValue).where(TaskPropertyValue.task_id == dup["id"])
    )
    dup_list = dup_rows.all()
    assert len(dup_list) == 1


# ---------------------------------------------------------------------------
# Filtering via conditions query param (property_values virtual field)
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_list_tasks_filter_by_property_text_eq(
    client: AsyncClient, session: AsyncSession
):
    user = await create_user(session, email="u@example.com")
    guild = await create_guild(session)
    await create_guild_membership(session, user=user, guild=guild, role=GuildRole.admin)
    initiative = await create_initiative(session, guild, user, name="Init")
    project = await create_project(session, initiative, user, name="P")
    task_match = await _create_task(session, project, "Match")
    task_other = await _create_task(session, project, "Other")

    defn = await create_property_definition(
        session, initiative, name="Tag", type=PropertyType.text
    )
    headers = get_guild_headers(guild, user)

    await client.put(
        f"/api/v1/tasks/{task_match.id}/properties",
        headers=headers,
        json={"values": [{"property_id": defn.id, "value": "findme"}]},
    )
    await client.put(
        f"/api/v1/tasks/{task_other.id}/properties",
        headers=headers,
        json={"values": [{"property_id": defn.id, "value": "skip"}]},
    )

    conditions = json.dumps([
        {"field": "project_id", "op": "eq", "value": project.id},
        {
            "field": "property_values",
            "op": "eq",
            "value": {"property_id": defn.id, "value": "findme"},
        },
    ])
    response = await client.get(
        f"/api/v1/tasks/?conditions={conditions}", headers=headers
    )
    assert response.status_code == 200
    ids = {item["id"] for item in response.json()["items"]}
    assert task_match.id in ids
    assert task_other.id not in ids


@pytest.mark.integration
async def test_list_tasks_filter_by_property_multi_select(
    client: AsyncClient, session: AsyncSession
):
    user = await create_user(session, email="u@example.com")
    guild = await create_guild(session)
    await create_guild_membership(session, user=user, guild=guild, role=GuildRole.admin)
    initiative = await create_initiative(session, guild, user, name="Init")
    project = await create_project(session, initiative, user, name="P")
    task_a = await _create_task(session, project, "A")
    task_b = await _create_task(session, project, "B")

    defn = await create_property_definition(
        session, initiative, name="Labels", type=PropertyType.multi_select,
        options=[{"value": "alpha", "label": "Alpha"}, {"value": "beta", "label": "Beta"}],
    )
    headers = get_guild_headers(guild, user)

    await client.put(
        f"/api/v1/tasks/{task_a.id}/properties",
        headers=headers,
        json={"values": [{"property_id": defn.id, "value": ["alpha"]}]},
    )
    await client.put(
        f"/api/v1/tasks/{task_b.id}/properties",
        headers=headers,
        json={"values": [{"property_id": defn.id, "value": ["beta"]}]},
    )

    conditions = json.dumps([
        {"field": "project_id", "op": "eq", "value": project.id},
        {
            "field": "property_values",
            "op": "eq",
            "value": {"property_id": defn.id, "value": ["alpha"]},
        },
    ])
    response = await client.get(
        f"/api/v1/tasks/?conditions={conditions}", headers=headers
    )
    assert response.status_code == 200
    ids = {item["id"] for item in response.json()["items"]}
    assert task_a.id in ids
    assert task_b.id not in ids
