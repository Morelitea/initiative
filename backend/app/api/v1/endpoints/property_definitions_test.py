"""
Integration tests for property definition endpoints.

Covers /api/v1/property-definitions CRUD including:
- RLS initiative isolation
- Union-across-initiatives list behavior
- Duplicate-name protection (per initiative)
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
# GET / — scope behavior
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_list_property_definitions_returns_union_across_initiatives(
    client: AsyncClient, session: AsyncSession
):
    """Without ``initiative_id`` the list endpoint returns the caller's
    accessible union — definitions across every initiative they're in."""
    user = await create_user(session, email="user@example.com")
    guild = await create_guild(session)
    await create_guild_membership(session, user=user, guild=guild, role=GuildRole.admin)

    init_a = await create_initiative(session, guild, user, name="A")
    init_b = await create_initiative(session, guild, user, name="B")

    defn_a = await create_property_definition(session, init_a, name="In A")
    defn_b = await create_property_definition(session, init_b, name="In B")

    response = await client.get(
        "/api/v1/property-definitions/", headers=get_guild_headers(guild, user)
    )
    assert response.status_code == 200
    ids = {item["id"] for item in response.json()}
    assert defn_a.id in ids
    assert defn_b.id in ids


@pytest.mark.integration
async def test_list_property_definitions_filtered_by_initiative_id(
    client: AsyncClient, session: AsyncSession
):
    """``?initiative_id=X`` filters to that initiative's definitions only."""
    user = await create_user(session, email="user@example.com")
    guild = await create_guild(session)
    await create_guild_membership(session, user=user, guild=guild, role=GuildRole.admin)

    init_a = await create_initiative(session, guild, user, name="A")
    init_b = await create_initiative(session, guild, user, name="B")

    defn_a = await create_property_definition(session, init_a, name="In A")
    defn_b = await create_property_definition(session, init_b, name="In B")

    response = await client.get(
        f"/api/v1/property-definitions/?initiative_id={init_a.id}",
        headers=get_guild_headers(guild, user),
    )
    assert response.status_code == 200
    ids = {item["id"] for item in response.json()}
    assert defn_a.id in ids
    assert defn_b.id not in ids


@pytest.mark.integration
async def test_list_property_definitions_scoped_by_initiative_id_query(
    client: AsyncClient, session: AsyncSession
):
    """Requesting a specific ``initiative_id`` scopes the result even when
    the caller technically has visibility across multiple initiatives
    (guild admin / superadmin bypass paths still respect explicit
    filtering through the query param).
    """
    admin = await create_user(session, email="admin@example.com")
    guild = await create_guild(session, creator=admin)
    await create_guild_membership(session, user=admin, guild=guild, role=GuildRole.admin)

    init_a = await create_initiative(session, guild, admin, name="A")
    init_b = await create_initiative(session, guild, admin, name="B")

    defn_a = await create_property_definition(session, init_a, name="In A")
    defn_b = await create_property_definition(session, init_b, name="In B")

    # Scoped to A
    response_a = await client.get(
        f"/api/v1/property-definitions/?initiative_id={init_a.id}",
        headers=get_guild_headers(guild, admin),
    )
    assert response_a.status_code == 200
    ids_a = {item["id"] for item in response_a.json()}
    assert defn_a.id in ids_a
    assert defn_b.id not in ids_a

    # Scoped to B
    response_b = await client.get(
        f"/api/v1/property-definitions/?initiative_id={init_b.id}",
        headers=get_guild_headers(guild, admin),
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
    initiative = await create_initiative(session, guild, user, name="Init")

    headers = get_guild_headers(guild, user)
    payload = {
        "name": "Status",
        "type": "text",
        "position": 1.0,
        "initiative_id": initiative.id,
    }
    response = await client.post(
        "/api/v1/property-definitions/", headers=headers, json=payload
    )

    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Status"
    assert data["type"] == "text"
    assert data["initiative_id"] == initiative.id


@pytest.mark.integration
async def test_create_rejected_when_not_initiative_member(
    client: AsyncClient, session: AsyncSession
):
    """A plain (non-admin) guild member can't create definitions on an
    initiative they don't belong to.
    """
    admin = await create_user(session, email="admin@example.com")
    alice = await create_user(session, email="alice@example.com")
    bob = await create_user(session, email="bob@example.com")
    guild = await create_guild(session, creator=admin)
    await create_guild_membership(session, user=admin, guild=guild, role=GuildRole.admin)
    await create_guild_membership(session, user=alice, guild=guild, role=GuildRole.member)
    await create_guild_membership(session, user=bob, guild=guild, role=GuildRole.member)

    # Alice's initiative; Bob is NOT a member.
    initiative = await create_initiative(session, guild, alice, name="Init")

    headers = get_guild_headers(guild, bob)
    payload = {
        "name": "Foo",
        "type": "text",
        "initiative_id": initiative.id,
    }
    response = await client.post(
        "/api/v1/property-definitions/", headers=headers, json=payload
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "PROPERTY_NOT_INITIATIVE_MEMBER"


@pytest.mark.integration
async def test_create_select_requires_options(
    client: AsyncClient, session: AsyncSession
):
    user = await create_user(session, email="admin@example.com")
    guild = await create_guild(session)
    await create_guild_membership(session, user=user, guild=guild, role=GuildRole.admin)
    initiative = await create_initiative(session, guild, user, name="Init")

    headers = get_guild_headers(guild, user)
    payload = {"name": "State", "type": "select", "initiative_id": initiative.id}
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
    initiative = await create_initiative(session, guild, user, name="Init")

    await create_property_definition(session, initiative, name="Priority")

    headers = get_guild_headers(guild, user)
    payload = {"name": "priority", "type": "text", "initiative_id": initiative.id}
    response = await client.post(
        "/api/v1/property-definitions/", headers=headers, json=payload
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "PROPERTY_NAME_ALREADY_EXISTS"


@pytest.mark.integration
async def test_create_same_name_in_different_initiatives_allowed(
    client: AsyncClient, session: AsyncSession
):
    """The uniqueness index is on (initiative_id, lower(name)) — two
    initiatives can each have their own 'Priority' without clashing."""
    user = await create_user(session, email="admin@example.com")
    guild = await create_guild(session)
    await create_guild_membership(session, user=user, guild=guild, role=GuildRole.admin)
    init_a = await create_initiative(session, guild, user, name="A")
    init_b = await create_initiative(session, guild, user, name="B")

    await create_property_definition(session, init_a, name="Priority")

    headers = get_guild_headers(guild, user)
    payload = {"name": "Priority", "type": "text", "initiative_id": init_b.id}
    response = await client.post(
        "/api/v1/property-definitions/", headers=headers, json=payload
    )
    assert response.status_code == 201


@pytest.mark.integration
async def test_create_select_duplicate_option_values_rejected(
    client: AsyncClient, session: AsyncSession
):
    user = await create_user(session, email="admin@example.com")
    guild = await create_guild(session)
    await create_guild_membership(session, user=user, guild=guild, role=GuildRole.admin)
    initiative = await create_initiative(session, guild, user, name="Init")

    headers = get_guild_headers(guild, user)
    payload = {
        "name": "Phase",
        "type": "select",
        "initiative_id": initiative.id,
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
    initiative = await create_initiative(session, guild, user, name="Init")
    defn = await create_property_definition(session, initiative, name="Phase")

    response = await client.get(
        f"/api/v1/property-definitions/{defn.id}",
        headers=get_guild_headers(guild, user),
    )

    assert response.status_code == 200
    assert response.json()["id"] == defn.id


@pytest.mark.integration
async def test_get_definition_for_missing_id_returns_404(
    client: AsyncClient, session: AsyncSession
):
    """Unknown definition id → 404 with the canonical error code."""
    user = await create_user(session, email="admin@example.com")
    guild = await create_guild(session)
    await create_guild_membership(session, user=user, guild=guild, role=GuildRole.admin)

    response = await client.get(
        "/api/v1/property-definitions/99999",
        headers=get_guild_headers(guild, user),
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
    initiative = await create_initiative(session, guild, user, name="Init")
    defn = await create_property_definition(
        session, initiative, name="Old Name", position=0.0
    )

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
    initiative = await create_initiative(session, guild, user, name="Init")
    defn = await create_property_definition(
        session, initiative, name="Immutable", type=PropertyType.text
    )

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
    initiative = await create_initiative(session, guild, user, name="Init")

    defn = await create_property_definition(
        session,
        initiative,
        name="Stage",
        type=PropertyType.select,
        options=[
            {"value": "draft", "label": "Draft"},
            {"value": "live", "label": "Live"},
        ],
    )

    # Attach a document value that uses the "live" slug.
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
    initiative = await create_initiative(session, guild, user, name="Init")
    defn = await create_property_definition(session, initiative, name="Meta")

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
    initiative = await create_initiative(session, guild, user, name="Init")
    defn = await create_property_definition(session, initiative, name="Owner Tag")

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


