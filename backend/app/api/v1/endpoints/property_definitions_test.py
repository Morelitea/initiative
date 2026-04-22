"""
Integration tests for property definition endpoints.

Covers /api/v1/property-definitions CRUD including:
- RLS guild isolation
- Duplicate-name protection
- Option validation on create/update
- Orphaned-value counting on PATCH
- Cascade delete to attached values
- /{id}/entities lookup
"""

import pytest
from httpx import AsyncClient
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.document import (
    Document,
    DocumentPermission,
    DocumentPermissionLevel,
    DocumentType,
)
from app.models.guild import GuildRole
from app.models.property import (
    DocumentPropertyValue,
    PropertyAppliesTo,
    PropertyDefinition,
    PropertyType,
    TaskPropertyValue,
)
from app.services import task_statuses as task_statuses_service
from app.testing import (
    create_document_property_value,
    create_guild,
    create_guild_membership,
    create_initiative,
    create_project,
    create_property_definition,
    create_task_property_value,
    create_user,
    get_guild_headers,
)


async def _create_task(session: AsyncSession, project, title: str = "Test Task"):
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


async def _create_document(
    session: AsyncSession,
    *,
    initiative,
    owner,
    title: str = "Doc With Property",
) -> Document:
    doc = Document(
        title=title,
        initiative_id=initiative.id,
        guild_id=initiative.guild_id,
        created_by_id=owner.id,
        updated_by_id=owner.id,
        document_type=DocumentType.native,
        content={},
    )
    session.add(doc)
    await session.flush()

    perm = DocumentPermission(
        document_id=doc.id,
        user_id=owner.id,
        level=DocumentPermissionLevel.owner,
        guild_id=initiative.guild_id,
    )
    session.add(perm)
    await session.commit()
    await session.refresh(doc)
    return doc


# ---------------------------------------------------------------------------
# GET / — guild isolation
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_list_property_definitions_isolated_per_guild(
    client: AsyncClient, session: AsyncSession
):
    """Definitions from guild B are not visible when listing with guild A header."""
    user = await create_user(session, email="user@example.com")
    guild_a = await create_guild(session, name="Guild A")
    guild_b = await create_guild(session, name="Guild B")
    await create_guild_membership(session, user=user, guild=guild_a, role=GuildRole.admin)
    await create_guild_membership(session, user=user, guild=guild_b, role=GuildRole.admin)

    defn_a = await create_property_definition(session, guild_a, name="In A")
    defn_b = await create_property_definition(session, guild_b, name="In B")

    # Fetch via guild A
    response_a = await client.get(
        "/api/v1/property-definitions/", headers=get_guild_headers(guild_a, user)
    )
    assert response_a.status_code == 200
    ids_a = {item["id"] for item in response_a.json()}
    assert defn_a.id in ids_a
    assert defn_b.id not in ids_a

    # Fetch via guild B
    response_b = await client.get(
        "/api/v1/property-definitions/", headers=get_guild_headers(guild_b, user)
    )
    assert response_b.status_code == 200
    ids_b = {item["id"] for item in response_b.json()}
    assert defn_b.id in ids_b
    assert defn_a.id not in ids_b


# ---------------------------------------------------------------------------
# POST /
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_create_text_property_definition(
    client: AsyncClient, session: AsyncSession
):
    user = await create_user(session, email="admin@example.com")
    guild = await create_guild(session)
    await create_guild_membership(session, user=user, guild=guild, role=GuildRole.admin)

    headers = get_guild_headers(guild, user)
    payload = {
        "name": "Status",
        "type": "text",
        "applies_to": "both",
        "position": 1.0,
    }
    response = await client.post(
        "/api/v1/property-definitions/", headers=headers, json=payload
    )

    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Status"
    assert data["type"] == "text"
    assert data["applies_to"] == "both"
    assert data["guild_id"] == guild.id


@pytest.mark.integration
async def test_create_select_requires_options(
    client: AsyncClient, session: AsyncSession
):
    user = await create_user(session, email="admin@example.com")
    guild = await create_guild(session)
    await create_guild_membership(session, user=user, guild=guild, role=GuildRole.admin)

    headers = get_guild_headers(guild, user)
    payload = {"name": "State", "type": "select"}  # no options
    response = await client.post(
        "/api/v1/property-definitions/", headers=headers, json=payload
    )

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert any("PROPERTY_OPTIONS_REQUIRED" in str(err) for err in detail)


@pytest.mark.integration
async def test_create_duplicate_name_case_insensitive_conflicts(
    client: AsyncClient, session: AsyncSession
):
    user = await create_user(session, email="admin@example.com")
    guild = await create_guild(session)
    await create_guild_membership(session, user=user, guild=guild, role=GuildRole.admin)

    await create_property_definition(session, guild, name="Priority")

    headers = get_guild_headers(guild, user)
    payload = {"name": "priority", "type": "text"}
    response = await client.post(
        "/api/v1/property-definitions/", headers=headers, json=payload
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "PROPERTY_NAME_ALREADY_EXISTS"


@pytest.mark.integration
async def test_create_select_duplicate_option_values_rejected(
    client: AsyncClient, session: AsyncSession
):
    user = await create_user(session, email="admin@example.com")
    guild = await create_guild(session)
    await create_guild_membership(session, user=user, guild=guild, role=GuildRole.admin)

    headers = get_guild_headers(guild, user)
    payload = {
        "name": "Phase",
        "type": "select",
        "options": [
            {"value": "draft", "label": "Draft"},
            {"value": "draft", "label": "Also Draft"},
        ],
    }
    response = await client.post(
        "/api/v1/property-definitions/", headers=headers, json=payload
    )

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert any("PROPERTY_DUPLICATE_OPTION_VALUE" in str(err) for err in detail)


# ---------------------------------------------------------------------------
# GET /{id}
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_get_definition_returns_definition(
    client: AsyncClient, session: AsyncSession
):
    user = await create_user(session, email="admin@example.com")
    guild = await create_guild(session)
    await create_guild_membership(session, user=user, guild=guild, role=GuildRole.admin)
    defn = await create_property_definition(session, guild, name="Phase")

    response = await client.get(
        f"/api/v1/property-definitions/{defn.id}",
        headers=get_guild_headers(guild, user),
    )

    assert response.status_code == 200
    assert response.json()["id"] == defn.id


@pytest.mark.integration
async def test_get_definition_non_member_guild_returns_404(
    client: AsyncClient, session: AsyncSession
):
    user = await create_user(session, email="user@example.com")
    guild_a = await create_guild(session, name="A")
    guild_b = await create_guild(session, name="B")
    await create_guild_membership(session, user=user, guild=guild_a, role=GuildRole.admin)

    # Definition lives in guild B, but user queries with guild A header.
    defn = await create_property_definition(session, guild_b, name="Other")

    response = await client.get(
        f"/api/v1/property-definitions/{defn.id}",
        headers=get_guild_headers(guild_a, user),
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "PROPERTY_DEFINITION_NOT_FOUND"


# ---------------------------------------------------------------------------
# PATCH /{id}
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_patch_renames_color_and_position(
    client: AsyncClient, session: AsyncSession
):
    user = await create_user(session, email="admin@example.com")
    guild = await create_guild(session)
    await create_guild_membership(session, user=user, guild=guild, role=GuildRole.admin)
    defn = await create_property_definition(session, guild, name="Old Name", position=0.0)

    headers = get_guild_headers(guild, user)
    payload = {"name": "New Name", "color": "#FF00AA", "position": 5.5}
    response = await client.patch(
        f"/api/v1/property-definitions/{defn.id}", headers=headers, json=payload
    )

    assert response.status_code == 200
    data = response.json()
    assert data["definition"]["name"] == "New Name"
    assert data["definition"]["color"] == "#FF00AA"
    assert data["definition"]["position"] == 5.5
    assert data["orphaned_value_count"] == 0


@pytest.mark.integration
async def test_patch_ignores_type_change_silently(
    client: AsyncClient, session: AsyncSession
):
    """The Update schema has no `type` field, so sending one is ignored."""
    user = await create_user(session, email="admin@example.com")
    guild = await create_guild(session)
    await create_guild_membership(session, user=user, guild=guild, role=GuildRole.admin)
    defn = await create_property_definition(session, guild, name="Immutable", type=PropertyType.text)

    headers = get_guild_headers(guild, user)
    payload = {"type": "number", "name": "Renamed"}
    response = await client.patch(
        f"/api/v1/property-definitions/{defn.id}", headers=headers, json=payload
    )

    assert response.status_code == 200
    assert response.json()["definition"]["type"] == "text"
    assert response.json()["definition"]["name"] == "Renamed"


@pytest.mark.integration
async def test_patch_removing_option_reports_orphaned_values(
    client: AsyncClient, session: AsyncSession
):
    """Removing an option on a select with attached values reports the orphans."""
    user = await create_user(session, email="admin@example.com")
    guild = await create_guild(session)
    await create_guild_membership(session, user=user, guild=guild, role=GuildRole.admin)

    defn = await create_property_definition(
        session,
        guild,
        name="Stage",
        type=PropertyType.select,
        options=[
            {"value": "draft", "label": "Draft"},
            {"value": "live", "label": "Live"},
        ],
    )

    # Attach a document value that uses the "live" slug.
    initiative = await create_initiative(session, guild, user, name="Init")
    doc = await _create_document(session, initiative=initiative, owner=user)
    await create_document_property_value(
        session, doc, defn, value_text="live"
    )

    headers = get_guild_headers(guild, user)
    # Remove "live" from the option list.
    payload = {"options": [{"value": "draft", "label": "Draft"}]}
    response = await client.patch(
        f"/api/v1/property-definitions/{defn.id}", headers=headers, json=payload
    )

    assert response.status_code == 200
    assert response.json()["orphaned_value_count"] >= 1

    # DB value should still be present — orphans are preserved.
    result = await session.exec(
        select(DocumentPropertyValue).where(
            DocumentPropertyValue.property_id == defn.id,
            DocumentPropertyValue.document_id == doc.id,
        )
    )
    assert result.one_or_none() is not None


# ---------------------------------------------------------------------------
# DELETE /{id}
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_delete_definition_cascades_to_values(
    client: AsyncClient, session: AsyncSession
):
    user = await create_user(session, email="admin@example.com")
    guild = await create_guild(session)
    await create_guild_membership(session, user=user, guild=guild, role=GuildRole.admin)
    defn = await create_property_definition(session, guild, name="Meta")

    initiative = await create_initiative(session, guild, user, name="Init")
    project = await create_project(session, initiative, user, name="Proj")
    task = await _create_task(session, project)
    doc = await _create_document(session, initiative=initiative, owner=user)

    await create_document_property_value(session, doc, defn, value_text="a doc value")
    await create_task_property_value(session, task, defn, value_text="a task value")

    headers = get_guild_headers(guild, user)
    response = await client.delete(
        f"/api/v1/property-definitions/{defn.id}", headers=headers
    )
    assert response.status_code == 204

    # Doc value row gone
    doc_val = await session.exec(
        select(DocumentPropertyValue).where(
            DocumentPropertyValue.property_id == defn.id
        )
    )
    assert doc_val.one_or_none() is None

    # Task value row gone
    task_val = await session.exec(
        select(TaskPropertyValue).where(TaskPropertyValue.property_id == defn.id)
    )
    assert task_val.one_or_none() is None

    # Definition gone
    defn_row = await session.exec(
        select(PropertyDefinition).where(PropertyDefinition.id == defn.id)
    )
    assert defn_row.one_or_none() is None


# ---------------------------------------------------------------------------
# GET /{id}/entities
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_get_entities_returns_attached_docs_and_tasks(
    client: AsyncClient, session: AsyncSession
):
    user = await create_user(session, email="admin@example.com")
    guild = await create_guild(session)
    await create_guild_membership(session, user=user, guild=guild, role=GuildRole.admin)
    defn = await create_property_definition(session, guild, name="Owner Tag")

    initiative = await create_initiative(session, guild, user, name="Init")
    project = await create_project(session, initiative, user, name="Proj")
    task = await _create_task(session, project, "Task 1")
    doc = await _create_document(session, initiative=initiative, owner=user, title="Doc 1")

    await create_document_property_value(session, doc, defn, value_text="x")
    await create_task_property_value(session, task, defn, value_text="y")

    response = await client.get(
        f"/api/v1/property-definitions/{defn.id}/entities",
        headers=get_guild_headers(guild, user),
    )
    assert response.status_code == 200
    data = response.json()
    task_ids = {entry["id"] for entry in data["tasks"]}
    doc_ids = {entry["id"] for entry in data["documents"]}
    assert task.id in task_ids
    assert doc.id in doc_ids


# ---------------------------------------------------------------------------
# applies_to enum round-trip (extra coverage beyond create-update matrix)
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_create_with_applies_to_task_persists(
    client: AsyncClient, session: AsyncSession
):
    user = await create_user(session, email="admin@example.com")
    guild = await create_guild(session)
    await create_guild_membership(session, user=user, guild=guild, role=GuildRole.admin)

    headers = get_guild_headers(guild, user)
    payload = {"name": "Task Only", "type": "text", "applies_to": "task"}
    response = await client.post(
        "/api/v1/property-definitions/", headers=headers, json=payload
    )

    assert response.status_code == 201
    assert response.json()["applies_to"] == PropertyAppliesTo.task.value
