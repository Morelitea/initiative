"""
Integration tests for the global documents scope.

Tests GET /api/v1/me/documents which returns documents created
by the current user across all guilds they belong to.
"""

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.guild import GuildRole
from app.testing import (
    Actor,
    create_guild,
    create_guild_membership,
    create_initiative,
)


async def _create_document(client, actor, initiative, title="Test Doc"):
    """Create a document via the API (sets created_by_id automatically)."""
    payload = {
        "title": title,
        "initiative_id": initiative.id,
    }
    response = await client.post(
        actor.g("/documents/"), headers=actor.headers, json=payload
    )
    assert response.status_code == 201
    return response.json()


@pytest.mark.integration
async def test_list_global_documents(client: AsyncClient, acting_user):
    """GET /me/documents should return documents created by the current user."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)

    doc = await _create_document(client, a, a.initiative, "My Doc")

    response = await client.get("/api/v1/me/documents", headers=a.headers)

    assert response.status_code == 200
    data = response.json()
    doc_ids = {d["id"] for d in data["items"]}
    assert doc["id"] in doc_ids
    assert data["total_count"] >= 1


@pytest.mark.integration
async def test_list_global_documents_excludes_others(client: AsyncClient, acting_user):
    """GET /me/documents should NOT return documents created by other users."""
    admin = await acting_user(guild_role=GuildRole.admin, initiative=True)
    other = await acting_user(
        guild_role=GuildRole.member,
        guild=admin.guild,
        initiative=admin.initiative,
        initiative_role="member",
    )

    # Admin creates a doc (via API, so created_by_id is set)
    admin_doc = await _create_document(client, admin, admin.initiative, "Admin's Doc")

    # Other user queries global docs — should not see admin's doc
    response = await client.get("/api/v1/me/documents", headers=other.headers)

    assert response.status_code == 200
    doc_ids = {d["id"] for d in response.json()["items"]}
    assert admin_doc["id"] not in doc_ids


@pytest.mark.integration
async def test_list_global_documents_guild_filter(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """GET /me/documents with guild_ids should restrict to specific guilds."""
    # First workspace via the actor seam; second guild + initiative for the SAME
    # user via factories (acting_user always mints a fresh user).
    a1 = await acting_user(guild_role=GuildRole.admin, initiative=True)
    user = a1.user
    guild1, init1 = a1.guild, a1.initiative

    guild2 = await create_guild(session, creator=user, name="Guild 2")
    await create_guild_membership(
        session, user=user, guild=guild2, role=GuildRole.admin
    )
    init2 = await create_initiative(session, guild2, user, name="Initiative")
    # A second actor view for the SAME user bound to guild2, so a2.g() addresses
    # guild2 while a2.headers is still the user's auth.
    a2 = Actor(user=user, headers=a1.headers, guild=guild2, initiative=init2)

    doc1 = await _create_document(client, a1, init1, "Doc in Guild 1")
    doc2 = await _create_document(client, a2, init2, "Doc in Guild 2")

    def keyed(resp):
        return {(d["initiative"]["guild_id"], d["id"]) for d in resp.json()["items"]}

    # No filter: documents from BOTH guilds are aggregated (per-schema ids
    # collide, so key by (guild_id, id)).
    response = await client.get("/api/v1/me/documents", headers=a1.headers)
    assert response.status_code == 200
    found = keyed(response)
    assert (guild1.id, doc1["id"]) in found
    assert (guild2.id, doc2["id"]) in found

    # Filtered to guild1: only guild1's document.
    response = await client.get(
        f"/api/v1/me/documents?guild_ids={guild1.id}", headers=a1.headers
    )
    assert response.status_code == 200
    found = keyed(response)
    assert (guild1.id, doc1["id"]) in found
    assert (guild2.id, doc2["id"]) not in found


@pytest.mark.integration
async def test_list_global_documents_search(client: AsyncClient, acting_user):
    """GET /me/documents with search should filter by document title."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)

    await _create_document(client, a, a.initiative, "Architecture Notes")
    await _create_document(client, a, a.initiative, "Meeting Summary")

    response = await client.get(
        "/api/v1/me/documents?search=architecture", headers=a.headers
    )

    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 1
    assert items[0]["title"] == "Architecture Notes"


@pytest.mark.integration
async def test_list_global_documents_pagination(client: AsyncClient, acting_user):
    """GET /me/documents should support pagination."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)

    for i in range(3):
        await _create_document(client, a, a.initiative, f"Doc {i}")

    # Page 1 with page_size=2
    response = await client.get(
        "/api/v1/me/documents?page=1&page_size=2", headers=a.headers
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data["items"]) == 2
    assert data["total_count"] == 3
    assert data["has_next"] is True

    # Page 2
    response = await client.get(
        "/api/v1/me/documents?page=2&page_size=2", headers=a.headers
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data["items"]) == 1
    assert data["has_next"] is False
