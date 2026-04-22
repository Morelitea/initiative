"""
Integration tests for document custom-property endpoints.

Covers:
- PUT /documents/{id}/properties replace-all semantics
- Value-type validation per property type
- RLS cross-guild isolation
- Documents list filtering via ``property_filters``
"""

import json

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
    PropertyType,
)
from app.testing import (
    create_guild,
    create_guild_membership,
    create_initiative,
    create_property_definition,
    create_user,
    get_guild_headers,
)


async def _create_document(
    session: AsyncSession,
    *,
    initiative,
    owner,
    title: str = "Doc",
    guild_id_override: int | None | str = "use_initiative",
) -> Document:
    """Create a native document owned by ``owner``.

    ``guild_id_override`` controls the ``Document.guild_id`` column:
    * ``"use_initiative"`` (default) uses ``initiative.guild_id``
    * ``None`` leaves the column NULL (global document)
    * any int explicitly sets the column
    """
    if guild_id_override == "use_initiative":
        doc_guild_id = initiative.guild_id
    else:
        doc_guild_id = guild_id_override

    doc = Document(
        title=title,
        initiative_id=initiative.id,
        guild_id=doc_guild_id,
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
# PUT replace-all
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_put_sets_multiple_property_values(
    client: AsyncClient, session: AsyncSession
):
    user = await create_user(session, email="u@example.com")
    guild = await create_guild(session)
    await create_guild_membership(session, user=user, guild=guild, role=GuildRole.admin)
    initiative = await create_initiative(session, guild, user, name="Init")
    doc = await _create_document(session, initiative=initiative, owner=user)

    text_defn = await create_property_definition(
        session, guild, name="Tag", type=PropertyType.text
    )
    number_defn = await create_property_definition(
        session, guild, name="Count", type=PropertyType.number
    )

    headers = get_guild_headers(guild, user)
    payload = {
        "values": [
            {"property_id": text_defn.id, "value": "alpha"},
            {"property_id": number_defn.id, "value": 42},
        ]
    }
    response = await client.put(
        f"/api/v1/documents/{doc.id}/properties", headers=headers, json=payload
    )

    assert response.status_code == 200
    data = response.json()
    props = {p["property_id"]: p for p in data["properties"]}
    assert text_defn.id in props
    assert number_defn.id in props
    assert props[text_defn.id]["value"] == "alpha"
    assert float(props[number_defn.id]["value"]) == 42.0


@pytest.mark.integration
async def test_put_empty_values_clears_existing_values(
    client: AsyncClient, session: AsyncSession
):
    user = await create_user(session, email="u@example.com")
    guild = await create_guild(session)
    await create_guild_membership(session, user=user, guild=guild, role=GuildRole.admin)
    initiative = await create_initiative(session, guild, user, name="Init")
    doc = await _create_document(session, initiative=initiative, owner=user)

    defn = await create_property_definition(session, guild, name="Tag", type=PropertyType.text)

    headers = get_guild_headers(guild, user)
    # Populate first
    await client.put(
        f"/api/v1/documents/{doc.id}/properties",
        headers=headers,
        json={"values": [{"property_id": defn.id, "value": "to be cleared"}]},
    )

    # Now clear
    response = await client.put(
        f"/api/v1/documents/{doc.id}/properties",
        headers=headers,
        json={"values": []},
    )
    assert response.status_code == 200
    assert response.json()["properties"] == []

    # Confirm in DB
    rows = await session.exec(
        select(DocumentPropertyValue).where(DocumentPropertyValue.document_id == doc.id)
    )
    assert rows.all() == []


# ---------------------------------------------------------------------------
# applies_to mismatch
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_put_applies_to_task_only_rejected_on_document(
    client: AsyncClient, session: AsyncSession
):
    user = await create_user(session, email="u@example.com")
    guild = await create_guild(session)
    await create_guild_membership(session, user=user, guild=guild, role=GuildRole.admin)
    initiative = await create_initiative(session, guild, user, name="Init")
    doc = await _create_document(session, initiative=initiative, owner=user)

    defn = await create_property_definition(
        session, guild, name="Task Only", type=PropertyType.text,
        applies_to=PropertyAppliesTo.task,
    )

    headers = get_guild_headers(guild, user)
    response = await client.put(
        f"/api/v1/documents/{doc.id}/properties",
        headers=headers,
        json={"values": [{"property_id": defn.id, "value": "no"}]},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "PROPERTY_APPLIES_TO_MISMATCH"


# ---------------------------------------------------------------------------
# Cross-guild isolation
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_put_cross_guild_definition_rejected(
    client: AsyncClient, session: AsyncSession
):
    user = await create_user(session, email="u@example.com")
    guild_a = await create_guild(session, name="A")
    guild_b = await create_guild(session, name="B")
    await create_guild_membership(session, user=user, guild=guild_a, role=GuildRole.admin)
    await create_guild_membership(session, user=user, guild=guild_b, role=GuildRole.admin)

    initiative_a = await create_initiative(session, guild_a, user, name="Init A")
    doc = await _create_document(session, initiative=initiative_a, owner=user)

    # Definition lives in guild B.
    defn_b = await create_property_definition(session, guild_b, name="Foreign")

    response = await client.put(
        f"/api/v1/documents/{doc.id}/properties",
        headers=get_guild_headers(guild_a, user),
        json={"values": [{"property_id": defn_b.id, "value": "x"}]},
    )
    assert response.status_code in {400, 404}
    # Service raises 404 DEFINITION_NOT_FOUND for cross-guild / unknown ids.
    assert response.json()["detail"] == "PROPERTY_DEFINITION_NOT_FOUND"


@pytest.mark.integration
async def test_put_properties_on_foreign_guild_document_returns_404(
    client: AsyncClient, session: AsyncSession
):
    """Document lives in guild B, client sends guild A header — 404."""
    user = await create_user(session, email="u@example.com")
    guild_a = await create_guild(session, name="A")
    guild_b = await create_guild(session, name="B")
    await create_guild_membership(session, user=user, guild=guild_a, role=GuildRole.admin)
    await create_guild_membership(session, user=user, guild=guild_b, role=GuildRole.admin)

    initiative_b = await create_initiative(session, guild_b, user, name="Init B")
    doc_b = await _create_document(session, initiative=initiative_b, owner=user)

    response = await client.put(
        f"/api/v1/documents/{doc_b.id}/properties",
        headers=get_guild_headers(guild_a, user),
        json={"values": []},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "DOCUMENT_NOT_FOUND"


# ---------------------------------------------------------------------------
# Type validation
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_put_text_value_against_number_type_rejected(
    client: AsyncClient, session: AsyncSession
):
    user = await create_user(session, email="u@example.com")
    guild = await create_guild(session)
    await create_guild_membership(session, user=user, guild=guild, role=GuildRole.admin)
    initiative = await create_initiative(session, guild, user, name="Init")
    doc = await _create_document(session, initiative=initiative, owner=user)

    defn = await create_property_definition(
        session, guild, name="Count", type=PropertyType.number
    )

    response = await client.put(
        f"/api/v1/documents/{doc.id}/properties",
        headers=get_guild_headers(guild, user),
        json={"values": [{"property_id": defn.id, "value": "not a number"}]},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "PROPERTY_INVALID_VALUE_FOR_TYPE"


@pytest.mark.integration
async def test_put_select_unknown_option_rejected(
    client: AsyncClient, session: AsyncSession
):
    user = await create_user(session, email="u@example.com")
    guild = await create_guild(session)
    await create_guild_membership(session, user=user, guild=guild, role=GuildRole.admin)
    initiative = await create_initiative(session, guild, user, name="Init")
    doc = await _create_document(session, initiative=initiative, owner=user)

    defn = await create_property_definition(
        session, guild, name="Phase", type=PropertyType.select,
        options=[{"value": "draft", "label": "Draft"}],
    )

    response = await client.put(
        f"/api/v1/documents/{doc.id}/properties",
        headers=get_guild_headers(guild, user),
        json={"values": [{"property_id": defn.id, "value": "nope"}]},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "PROPERTY_OPTION_NOT_IN_DEFINITION"


@pytest.mark.integration
async def test_put_multi_select_unknown_option_rejected(
    client: AsyncClient, session: AsyncSession
):
    user = await create_user(session, email="u@example.com")
    guild = await create_guild(session)
    await create_guild_membership(session, user=user, guild=guild, role=GuildRole.admin)
    initiative = await create_initiative(session, guild, user, name="Init")
    doc = await _create_document(session, initiative=initiative, owner=user)

    defn = await create_property_definition(
        session, guild, name="Tags", type=PropertyType.multi_select,
        options=[{"value": "one", "label": "One"}, {"value": "two", "label": "Two"}],
    )

    response = await client.put(
        f"/api/v1/documents/{doc.id}/properties",
        headers=get_guild_headers(guild, user),
        json={"values": [{"property_id": defn.id, "value": ["one", "ghost"]}]},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "PROPERTY_OPTION_NOT_IN_DEFINITION"


@pytest.mark.integration
async def test_put_user_reference_non_member_rejected(
    client: AsyncClient, session: AsyncSession
):
    user = await create_user(session, email="u@example.com")
    outsider = await create_user(session, email="outsider@example.com")
    guild = await create_guild(session)
    await create_guild_membership(session, user=user, guild=guild, role=GuildRole.admin)
    # NOTE: outsider is intentionally *not* a member of guild.

    initiative = await create_initiative(session, guild, user, name="Init")
    doc = await _create_document(session, initiative=initiative, owner=user)

    defn = await create_property_definition(
        session, guild, name="Owner", type=PropertyType.user_reference
    )

    response = await client.put(
        f"/api/v1/documents/{doc.id}/properties",
        headers=get_guild_headers(guild, user),
        json={"values": [{"property_id": defn.id, "value": outsider.id}]},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "PROPERTY_USER_NOT_IN_GUILD"


@pytest.mark.integration
async def test_put_url_accepts_valid_url_and_rejects_invalid(
    client: AsyncClient, session: AsyncSession
):
    user = await create_user(session, email="u@example.com")
    guild = await create_guild(session)
    await create_guild_membership(session, user=user, guild=guild, role=GuildRole.admin)
    initiative = await create_initiative(session, guild, user, name="Init")
    doc = await _create_document(session, initiative=initiative, owner=user)

    defn = await create_property_definition(
        session, guild, name="Site", type=PropertyType.url
    )

    headers = get_guild_headers(guild, user)
    # Valid URL
    response = await client.put(
        f"/api/v1/documents/{doc.id}/properties",
        headers=headers,
        json={"values": [{"property_id": defn.id, "value": "https://example.com"}]},
    )
    assert response.status_code == 200
    values = {p["property_id"]: p["value"] for p in response.json()["properties"]}
    assert values[defn.id] == "https://example.com"

    # Invalid URL string
    bad = await client.put(
        f"/api/v1/documents/{doc.id}/properties",
        headers=headers,
        json={"values": [{"property_id": defn.id, "value": "not a url"}]},
    )
    assert bad.status_code == 400
    assert bad.json()["detail"] == "PROPERTY_INVALID_VALUE_FOR_TYPE"


# ---------------------------------------------------------------------------
# Global documents (guild_id IS NULL on the document row)
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_put_properties_on_doc_with_null_guild_id(
    client: AsyncClient, session: AsyncSession
):
    """Documents whose own ``guild_id`` column is NULL still support property attach.

    Access resolves through the owner's DocumentPermission + the
    document's initiative (whose ``guild_id`` matches the request header).
    """
    user = await create_user(session, email="u@example.com")
    guild = await create_guild(session)
    await create_guild_membership(session, user=user, guild=guild, role=GuildRole.admin)
    # create_initiative already adds the creator as PM via the factory.
    initiative = await create_initiative(session, guild, user, name="Init")

    # guild_id_override=None produces a doc with Document.guild_id IS NULL
    doc = await _create_document(
        session, initiative=initiative, owner=user, guild_id_override=None
    )
    defn = await create_property_definition(session, guild, name="Tag", type=PropertyType.text)

    response = await client.put(
        f"/api/v1/documents/{doc.id}/properties",
        headers=get_guild_headers(guild, user),
        json={"values": [{"property_id": defn.id, "value": "alpha"}]},
    )

    assert response.status_code == 200
    props = {p["property_id"]: p["value"] for p in response.json()["properties"]}
    assert props[defn.id] == "alpha"


# ---------------------------------------------------------------------------
# Documents list — property_filters query param
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_list_documents_property_filter_text_eq(
    client: AsyncClient, session: AsyncSession
):
    user = await create_user(session, email="u@example.com")
    guild = await create_guild(session)
    await create_guild_membership(session, user=user, guild=guild, role=GuildRole.admin)
    initiative = await create_initiative(session, guild, user, name="Init")

    defn = await create_property_definition(session, guild, name="Tag", type=PropertyType.text)

    doc_match = await _create_document(session, initiative=initiative, owner=user, title="Match")
    doc_other = await _create_document(session, initiative=initiative, owner=user, title="Other")

    headers = get_guild_headers(guild, user)
    await client.put(
        f"/api/v1/documents/{doc_match.id}/properties",
        headers=headers,
        json={"values": [{"property_id": defn.id, "value": "findme"}]},
    )
    await client.put(
        f"/api/v1/documents/{doc_other.id}/properties",
        headers=headers,
        json={"values": [{"property_id": defn.id, "value": "skip"}]},
    )

    filt = json.dumps([
        {"property_id": defn.id, "op": "eq", "value": "findme"}
    ])
    response = await client.get(
        f"/api/v1/documents/?initiative_id={initiative.id}&property_filters={filt}",
        headers=headers,
    )
    assert response.status_code == 200
    ids = {item["id"] for item in response.json()["items"]}
    assert doc_match.id in ids
    assert doc_other.id not in ids


@pytest.mark.integration
async def test_list_documents_property_filter_number_eq(
    client: AsyncClient, session: AsyncSession
):
    user = await create_user(session, email="u@example.com")
    guild = await create_guild(session)
    await create_guild_membership(session, user=user, guild=guild, role=GuildRole.admin)
    initiative = await create_initiative(session, guild, user, name="Init")

    defn = await create_property_definition(
        session, guild, name="Score", type=PropertyType.number
    )

    docs = [
        await _create_document(session, initiative=initiative, owner=user, title="D1"),
        await _create_document(session, initiative=initiative, owner=user, title="D2"),
        await _create_document(session, initiative=initiative, owner=user, title="D3"),
    ]

    headers = get_guild_headers(guild, user)
    for doc, score in zip(docs, [10, 20, 30]):
        await client.put(
            f"/api/v1/documents/{doc.id}/properties",
            headers=headers,
            json={"values": [{"property_id": defn.id, "value": score}]},
        )

    filt = json.dumps([{"property_id": defn.id, "op": "eq", "value": 20}])
    response = await client.get(
        f"/api/v1/documents/?initiative_id={initiative.id}&property_filters={filt}",
        headers=headers,
    )
    assert response.status_code == 200
    ids = {item["id"] for item in response.json()["items"]}
    assert docs[1].id in ids
    assert docs[0].id not in ids
    assert docs[2].id not in ids


@pytest.mark.integration
async def test_list_documents_property_filter_multi_select_contains(
    client: AsyncClient, session: AsyncSession
):
    """multi_select uses JSONB @> (contains) semantics."""
    user = await create_user(session, email="u@example.com")
    guild = await create_guild(session)
    await create_guild_membership(session, user=user, guild=guild, role=GuildRole.admin)
    initiative = await create_initiative(session, guild, user, name="Init")

    defn = await create_property_definition(
        session, guild, name="Labels", type=PropertyType.multi_select,
        options=[
            {"value": "alpha", "label": "Alpha"},
            {"value": "beta", "label": "Beta"},
            {"value": "gamma", "label": "Gamma"},
        ],
    )

    doc_with_alpha = await _create_document(session, initiative=initiative, owner=user, title="A")
    doc_no_alpha = await _create_document(session, initiative=initiative, owner=user, title="N")

    headers = get_guild_headers(guild, user)
    await client.put(
        f"/api/v1/documents/{doc_with_alpha.id}/properties",
        headers=headers,
        json={"values": [{"property_id": defn.id, "value": ["alpha", "beta"]}]},
    )
    await client.put(
        f"/api/v1/documents/{doc_no_alpha.id}/properties",
        headers=headers,
        json={"values": [{"property_id": defn.id, "value": ["gamma"]}]},
    )

    filt = json.dumps([{"property_id": defn.id, "op": "eq", "value": ["alpha"]}])
    response = await client.get(
        f"/api/v1/documents/?initiative_id={initiative.id}&property_filters={filt}",
        headers=headers,
    )
    assert response.status_code == 200
    ids = {item["id"] for item in response.json()["items"]}
    assert doc_with_alpha.id in ids
    assert doc_no_alpha.id not in ids


@pytest.mark.integration
async def test_list_documents_invalid_property_filters_json_returns_400(
    client: AsyncClient, session: AsyncSession
):
    user = await create_user(session, email="u@example.com")
    guild = await create_guild(session)
    await create_guild_membership(session, user=user, guild=guild, role=GuildRole.admin)
    initiative = await create_initiative(session, guild, user, name="Init")

    response = await client.get(
        f"/api/v1/documents/?initiative_id={initiative.id}&property_filters=not-json",
        headers=get_guild_headers(guild, user),
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "QUERY_INVALID_CONDITIONS"


@pytest.mark.integration
async def test_list_documents_too_many_property_filters_returns_400(
    client: AsyncClient, session: AsyncSession
):
    user = await create_user(session, email="u@example.com")
    guild = await create_guild(session)
    await create_guild_membership(session, user=user, guild=guild, role=GuildRole.admin)
    initiative = await create_initiative(session, guild, user, name="Init")

    # Fabricate 6 predicates (cap is 5); ids don't need to exist.
    filt = json.dumps([
        {"property_id": i, "op": "eq", "value": "x"} for i in range(1, 7)
    ])
    response = await client.get(
        f"/api/v1/documents/?initiative_id={initiative.id}&property_filters={filt}",
        headers=get_guild_headers(guild, user),
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "QUERY_INVALID_CONDITIONS"
