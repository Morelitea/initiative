"""
Integration tests for the global documents scope.

Tests GET /api/v1/documents/?scope=global which returns documents created
by the current user across all guilds they belong to.
"""

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.guild import GuildRole
from app.testing.factories import (
    create_guild,
    create_guild_membership,
    create_initiative,
    create_user,
    get_guild_headers,
)


async def _create_document(client, guild, user, initiative, title="Test Doc"):
    """Create a document via the API (sets created_by_id automatically)."""
    headers = get_guild_headers(guild, user)
    payload = {
        "title": title,
        "initiative_id": initiative.id,
    }
    response = await client.post("/api/v1/documents/", headers=headers, json=payload)
    assert response.status_code == 201
    return response.json()


async def _setup_guild_with_initiative(session, user, *, guild_name="Test Guild"):
    """Create a guild, membership, and initiative for the user."""
    guild = await create_guild(session, creator=user, name=guild_name)
    await create_guild_membership(
        session, user=user, guild=guild, role=GuildRole.admin
    )
    initiative = await create_initiative(session, guild, user, name="Initiative")
    return guild, initiative


@pytest.mark.integration
async def test_list_global_documents(client: AsyncClient, session: AsyncSession):
    """scope=global should return documents created by the current user."""
    user = await create_user(session, email="user@example.com")
    guild, initiative = await _setup_guild_with_initiative(session, user)

    doc = await _create_document(client, guild, user, initiative, "My Doc")

    headers = get_guild_headers(guild, user)
    response = await client.get("/api/v1/documents/?scope=global", headers=headers)

    assert response.status_code == 200
    data = response.json()
    doc_ids = {d["id"] for d in data["items"]}
    assert doc["id"] in doc_ids
    assert data["total_count"] >= 1


@pytest.mark.integration
async def test_list_global_documents_excludes_others(
    client: AsyncClient, session: AsyncSession
):
    """scope=global should NOT return documents created by other users."""
    admin = await create_user(session, email="admin@example.com")
    other = await create_user(session, email="other@example.com")
    guild, initiative = await _setup_guild_with_initiative(session, admin)
    await create_guild_membership(session, user=other, guild=guild)

    # Admin creates a doc (via API, so created_by_id is set)
    admin_doc = await _create_document(
        client, guild, admin, initiative, "Admin's Doc"
    )

    # Other user queries global docs — should not see admin's doc
    headers = get_guild_headers(guild, other)
    response = await client.get("/api/v1/documents/?scope=global", headers=headers)

    assert response.status_code == 200
    doc_ids = {d["id"] for d in response.json()["items"]}
    assert admin_doc["id"] not in doc_ids


@pytest.mark.integration
async def test_list_global_documents_guild_filter(
    client: AsyncClient, session: AsyncSession
):
    """scope=global with guild_ids should restrict to specific guilds."""
    user = await create_user(session, email="user@example.com")
    guild1, init1 = await _setup_guild_with_initiative(
        session, user, guild_name="Guild 1"
    )
    guild2, init2 = await _setup_guild_with_initiative(
        session, user, guild_name="Guild 2"
    )

    doc1 = await _create_document(client, guild1, user, init1, "Doc in Guild 1")
    doc2 = await _create_document(client, guild2, user, init2, "Doc in Guild 2")

    headers = get_guild_headers(guild1, user)
    response = await client.get(
        f"/api/v1/documents/?scope=global&guild_ids={guild1.id}", headers=headers
    )

    assert response.status_code == 200
    doc_ids = {d["id"] for d in response.json()["items"]}
    assert doc1["id"] in doc_ids
    assert doc2["id"] not in doc_ids


@pytest.mark.integration
async def test_list_global_documents_search(
    client: AsyncClient, session: AsyncSession
):
    """scope=global with search should filter by document title."""
    user = await create_user(session, email="user@example.com")
    guild, initiative = await _setup_guild_with_initiative(session, user)

    await _create_document(client, guild, user, initiative, "Architecture Notes")
    await _create_document(client, guild, user, initiative, "Meeting Summary")

    headers = get_guild_headers(guild, user)
    response = await client.get(
        "/api/v1/documents/?scope=global&search=architecture", headers=headers
    )

    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 1
    assert items[0]["title"] == "Architecture Notes"


@pytest.mark.integration
async def test_list_global_documents_pagination(
    client: AsyncClient, session: AsyncSession
):
    """scope=global should support pagination."""
    user = await create_user(session, email="user@example.com")
    guild, initiative = await _setup_guild_with_initiative(session, user)

    for i in range(3):
        await _create_document(client, guild, user, initiative, f"Doc {i}")

    headers = get_guild_headers(guild, user)

    # Page 1 with page_size=2
    response = await client.get(
        "/api/v1/documents/?scope=global&page=1&page_size=2", headers=headers
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data["items"]) == 2
    assert data["total_count"] == 3
    assert data["has_next"] is True

    # Page 2
    response = await client.get(
        "/api/v1/documents/?scope=global&page=2&page_size=2", headers=headers
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data["items"]) == 1
    assert data["has_next"] is False
