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

from app.models.platform.guild import GuildRole
from app.models.tenant.property import (
    DocumentPropertyValue,
    PropertyDefinition,
    PropertyType,
    TaskPropertyValue,
)
from app.testing import (
    create_document,
    create_document_property_value,
    create_initiative,
    create_project,
    create_property_definition,
    create_task,
    create_task_property_value,
)


# ---------------------------------------------------------------------------
# GET / — scope behavior
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_list_property_definitions_returns_union_across_initiatives(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Without ``initiative_id`` the list endpoint returns the caller's
    accessible union — definitions across every initiative they're in."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    init_a = a.initiative
    init_b = await create_initiative(session, a.guild, a.user, name="B")

    defn_a = await create_property_definition(session, init_a, name="In A")
    defn_b = await create_property_definition(session, init_b, name="In B")

    response = await client.get(
        a.g("/property-definitions/"),
        headers=a.headers,
    )
    assert response.status_code == 200
    ids = {item["id"] for item in response.json()}
    assert defn_a.id in ids
    assert defn_b.id in ids


@pytest.mark.integration
async def test_list_property_definitions_filtered_by_initiative_id(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """``?initiative_id=X`` filters to that initiative's definitions only."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    init_a = a.initiative
    init_b = await create_initiative(session, a.guild, a.user, name="B")

    defn_a = await create_property_definition(session, init_a, name="In A")
    defn_b = await create_property_definition(session, init_b, name="In B")

    response = await client.get(
        a.g(f"/property-definitions/?initiative_id={init_a.id}"),
        headers=a.headers,
    )
    assert response.status_code == 200
    ids = {item["id"] for item in response.json()}
    assert defn_a.id in ids
    assert defn_b.id not in ids


@pytest.mark.integration
async def test_list_property_definitions_scoped_by_initiative_id_query(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Requesting a specific ``initiative_id`` scopes the result even when
    the caller technically has visibility across multiple initiatives
    (guild admin / superadmin bypass paths still respect explicit
    filtering through the query param).
    """
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    init_a = a.initiative
    init_b = await create_initiative(session, a.guild, a.user, name="B")

    defn_a = await create_property_definition(session, init_a, name="In A")
    defn_b = await create_property_definition(session, init_b, name="In B")

    # Scoped to A
    response_a = await client.get(
        a.g(f"/property-definitions/?initiative_id={init_a.id}"),
        headers=a.headers,
    )
    assert response_a.status_code == 200
    ids_a = {item["id"] for item in response_a.json()}
    assert defn_a.id in ids_a
    assert defn_b.id not in ids_a

    # Scoped to B
    response_b = await client.get(
        a.g(f"/property-definitions/?initiative_id={init_b.id}"),
        headers=a.headers,
    )
    assert response_b.status_code == 200
    ids_b = {item["id"] for item in response_b.json()}
    assert defn_b.id in ids_b
    assert defn_a.id not in ids_b


# ---------------------------------------------------------------------------
# POST /
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_create_text_property_definition(client: AsyncClient, acting_user):
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)

    payload = {
        "name": "Status",
        "type": "text",
        "position": 1.0,
        "initiative_id": a.initiative.id,
    }
    response = await client.post(
        a.g("/property-definitions/"), headers=a.headers, json=payload
    )

    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Status"
    assert data["type"] == "text"
    assert data["initiative_id"] == a.initiative.id


@pytest.mark.integration
async def test_create_rejected_when_not_initiative_member(
    client: AsyncClient, acting_user
):
    """A plain (non-admin) guild member can't create definitions on an
    initiative they don't belong to.
    """
    # Alice owns the initiative; Bob is a guild member but NOT an initiative member.
    alice = await acting_user(guild_role=GuildRole.member, initiative=True)
    bob = await acting_user(guild_role=GuildRole.member, guild=alice.guild)

    payload = {
        "name": "Foo",
        "type": "text",
        "initiative_id": alice.initiative.id,
    }
    response = await client.post(
        bob.g("/property-definitions/"), headers=bob.headers, json=payload
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "PROPERTY_NOT_INITIATIVE_MEMBER"


@pytest.mark.integration
async def test_create_allowed_for_initiative_member(client: AsyncClient, acting_user):
    """A plain (non-admin) guild member who belongs to the initiative can
    create a definition on it.

    This is the schema-per-guild regression case: the membership check now
    runs on the routed request session against the active guild's schema,
    so a legitimate member is no longer false-403'd by a lookup against the
    frozen ``public`` backup.
    """
    admin = await acting_user(guild_role=GuildRole.admin, initiative=True)
    member = await acting_user(
        guild_role=GuildRole.member,
        guild=admin.guild,
        initiative=admin.initiative,
        initiative_role="member",
    )

    payload = {
        "name": "Owner Tag",
        "type": "text",
        "initiative_id": admin.initiative.id,
    }
    response = await client.post(
        member.g("/property-definitions/"), headers=member.headers, json=payload
    )

    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Owner Tag"
    assert data["initiative_id"] == admin.initiative.id


@pytest.mark.integration
async def test_create_rejected_for_guild_member_not_in_initiative(
    client: AsyncClient, acting_user
):
    """A guild member who is NOT in the target initiative is rejected with
    the canonical NOT_INITIATIVE_MEMBER code."""
    # Admin's initiative; outsider is a guild member but not an initiative member.
    admin = await acting_user(guild_role=GuildRole.admin, initiative=True)
    outsider = await acting_user(guild_role=GuildRole.member, guild=admin.guild)

    payload = {
        "name": "Foo",
        "type": "text",
        "initiative_id": admin.initiative.id,
    }
    response = await client.post(
        outsider.g("/property-definitions/"), headers=outsider.headers, json=payload
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "PROPERTY_NOT_INITIATIVE_MEMBER"


@pytest.mark.integration
async def test_create_allowed_for_guild_admin_not_in_initiative(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """A guild admin can create a definition on any initiative in their
    guild even without an explicit initiative-member row — mirroring the
    restrictive RLS policy's admin bypass, now resolved off
    ``GuildContext.role``."""
    # The creator owns the initiative; the guild admin is not a member of it.
    creator = await acting_user(guild_role=GuildRole.member, initiative=True)
    guild_admin = await acting_user(guild_role=GuildRole.admin, guild=creator.guild)

    payload = {
        "name": "Admin Field",
        "type": "text",
        "initiative_id": creator.initiative.id,
    }
    response = await client.post(
        guild_admin.g("/property-definitions/"),
        headers=guild_admin.headers,
        json=payload,
    )

    assert response.status_code == 201
    assert response.json()["initiative_id"] == creator.initiative.id


@pytest.mark.integration
async def test_create_select_requires_options(client: AsyncClient, acting_user):
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)

    payload = {"name": "State", "type": "select", "initiative_id": a.initiative.id}
    response = await client.post(
        a.g("/property-definitions/"), headers=a.headers, json=payload
    )

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert any("PROPERTY_OPTIONS_REQUIRED" in str(err) for err in detail)


@pytest.mark.integration
async def test_create_duplicate_name_case_insensitive_conflicts(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)

    await create_property_definition(session, a.initiative, name="Priority")

    payload = {"name": "priority", "type": "text", "initiative_id": a.initiative.id}
    response = await client.post(
        a.g("/property-definitions/"), headers=a.headers, json=payload
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "PROPERTY_NAME_ALREADY_EXISTS"


@pytest.mark.integration
async def test_create_same_name_in_different_initiatives_allowed(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The uniqueness index is on (initiative_id, lower(name)) — two
    initiatives can each have their own 'Priority' without clashing."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    init_a = a.initiative
    init_b = await create_initiative(session, a.guild, a.user, name="B")

    await create_property_definition(session, init_a, name="Priority")

    payload = {"name": "Priority", "type": "text", "initiative_id": init_b.id}
    response = await client.post(
        a.g("/property-definitions/"), headers=a.headers, json=payload
    )
    assert response.status_code == 201


@pytest.mark.integration
async def test_create_select_duplicate_option_values_rejected(
    client: AsyncClient, acting_user
):
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)

    payload = {
        "name": "Phase",
        "type": "select",
        "initiative_id": a.initiative.id,
        "options": [
            {"value": "draft", "label": "Draft"},
            {"value": "draft", "label": "Also Draft"},
        ],
    }
    response = await client.post(
        a.g("/property-definitions/"), headers=a.headers, json=payload
    )

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert any("PROPERTY_DUPLICATE_OPTION_VALUE" in str(err) for err in detail)


# ---------------------------------------------------------------------------
# GET /{id}
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_get_definition_returns_definition(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    defn = await create_property_definition(session, a.initiative, name="Phase")

    response = await client.get(
        a.g(f"/property-definitions/{defn.id}"),
        headers=a.headers,
    )

    assert response.status_code == 200
    assert response.json()["id"] == defn.id


@pytest.mark.integration
async def test_get_definition_for_missing_id_returns_404(
    client: AsyncClient, acting_user
):
    """Unknown definition id → 404 with the canonical error code."""
    a = await acting_user(guild_role=GuildRole.admin)

    response = await client.get(
        a.g("/property-definitions/99999"),
        headers=a.headers,
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "PROPERTY_DEFINITION_NOT_FOUND"


# ---------------------------------------------------------------------------
# PATCH /{id}
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_patch_renames_color_and_position(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    defn = await create_property_definition(
        session, a.initiative, name="Old Name", position=0.0
    )

    payload = {"name": "New Name", "color": "#FF00AA", "position": 5.5}
    response = await client.patch(
        a.g(f"/property-definitions/{defn.id}"),
        headers=a.headers,
        json=payload,
    )

    assert response.status_code == 200
    data = response.json()
    assert data["definition"]["name"] == "New Name"
    assert data["definition"]["color"] == "#FF00AA"
    assert data["definition"]["position"] == 5.5
    assert data["orphaned_value_count"] == 0


@pytest.mark.integration
async def test_patch_ignores_type_change_silently(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The Update schema has no `type` field, so sending one is ignored."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    defn = await create_property_definition(
        session, a.initiative, name="Immutable", type=PropertyType.text
    )

    payload = {"type": "number", "name": "Renamed"}
    response = await client.patch(
        a.g(f"/property-definitions/{defn.id}"),
        headers=a.headers,
        json=payload,
    )

    assert response.status_code == 200
    assert response.json()["definition"]["type"] == "text"
    assert response.json()["definition"]["name"] == "Renamed"


@pytest.mark.integration
async def test_patch_removing_option_reports_orphaned_values(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Removing an option on a select with attached values reports the orphans."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)

    defn = await create_property_definition(
        session,
        a.initiative,
        name="Stage",
        type=PropertyType.select,
        options=[
            {"value": "draft", "label": "Draft"},
            {"value": "live", "label": "Live"},
        ],
    )

    # Attach a document value that uses the "live" slug.
    doc = await create_document(session, a.initiative, a.user)
    await create_document_property_value(session, doc, defn, value_text="live")

    # Remove "live" from the option list.
    payload = {"options": [{"value": "draft", "label": "Draft"}]}
    response = await client.patch(
        a.g(f"/property-definitions/{defn.id}"),
        headers=a.headers,
        json=payload,
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
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    defn = await create_property_definition(session, a.initiative, name="Meta")

    project = await create_project(session, a.initiative, a.user, name="Proj")
    task = await create_task(session, project)
    doc = await create_document(session, a.initiative, a.user)

    await create_document_property_value(session, doc, defn, value_text="a doc value")
    await create_task_property_value(session, task, defn, value_text="a task value")

    response = await client.delete(
        a.g(f"/property-definitions/{defn.id}"), headers=a.headers
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
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    defn = await create_property_definition(session, a.initiative, name="Owner Tag")

    project = await create_project(session, a.initiative, a.user, name="Proj")
    task = await create_task(session, project, title="Task 1")
    doc = await create_document(session, a.initiative, a.user, title="Doc 1")

    await create_document_property_value(session, doc, defn, value_text="x")
    await create_task_property_value(session, task, defn, value_text="y")

    response = await client.get(
        a.g(f"/property-definitions/{defn.id}/entities"),
        headers=a.headers,
    )
    assert response.status_code == 200
    data = response.json()
    task_ids = {entry["id"] for entry in data["tasks"]}
    doc_ids = {entry["id"] for entry in data["documents"]}
    assert task.id in task_ids
    assert doc.id in doc_ids
