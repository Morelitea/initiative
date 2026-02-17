"""
Integration tests for document endpoints — create with permissions.
"""

import pytest
from httpx import AsyncClient
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.guild import GuildRole
from app.models.initiative import InitiativeRoleModel
from app.testing.factories import (
    create_guild,
    create_guild_membership,
    create_initiative,
    create_initiative_member,
    create_user,
    get_guild_headers,
)


@pytest.mark.integration
async def test_create_document_with_permissions(
    client: AsyncClient, session: AsyncSession
):
    """Test creating a document with both role and user permissions."""
    admin = await create_user(session, email="admin@example.com")
    member = await create_user(session, email="member@example.com")
    guild = await create_guild(session)
    await create_guild_membership(session, user=admin, guild=guild, role=GuildRole.admin)
    await create_guild_membership(session, user=member, guild=guild)

    initiative = await create_initiative(session, guild, admin, name="Test Initiative")
    await create_initiative_member(session, initiative, member, role_name="member")

    # Find the member role
    result = await session.exec(
        select(InitiativeRoleModel).where(
            InitiativeRoleModel.initiative_id == initiative.id,
            InitiativeRoleModel.name == "member",
        )
    )
    member_role = result.one()

    headers = get_guild_headers(guild, admin)
    payload = {
        "title": "Doc With Permissions",
        "initiative_id": initiative.id,
        "role_permissions": [
            {"initiative_role_id": member_role.id, "level": "read"},
        ],
        "user_permissions": [
            {"user_id": member.id, "level": "write"},
        ],
    }

    response = await client.post("/api/v1/documents/", headers=headers, json=payload)

    assert response.status_code == 201
    data = response.json()
    assert data["title"] == "Doc With Permissions"

    # Owner permission exists
    perm_user_ids = {p["user_id"] for p in data["permissions"]}
    assert admin.id in perm_user_ids
    assert member.id in perm_user_ids

    # Role permission exists
    assert len(data["role_permissions"]) == 1
    assert data["role_permissions"][0]["initiative_role_id"] == member_role.id
    assert data["role_permissions"][0]["level"] == "read"

    # Member's user permission is write
    member_perm = next(p for p in data["permissions"] if p["user_id"] == member.id)
    assert member_perm["level"] == "write"


@pytest.mark.integration
async def test_create_document_without_permissions(
    client: AsyncClient, session: AsyncSession
):
    """Test creating a document without extra permissions yields only owner."""
    admin = await create_user(session, email="admin@example.com")
    guild = await create_guild(session)
    await create_guild_membership(session, user=admin, guild=guild, role=GuildRole.admin)

    initiative = await create_initiative(session, guild, admin, name="Test Initiative")

    headers = get_guild_headers(guild, admin)
    payload = {
        "title": "Doc No Perms",
        "initiative_id": initiative.id,
    }

    response = await client.post("/api/v1/documents/", headers=headers, json=payload)

    assert response.status_code == 201
    data = response.json()
    # Only the owner permission should exist
    assert len(data["permissions"]) == 1
    assert data["permissions"][0]["user_id"] == admin.id
    assert data["permissions"][0]["level"] == "owner"
    assert len(data["role_permissions"]) == 0


@pytest.mark.integration
async def test_create_document_rejects_foreign_initiative_role(
    client: AsyncClient, session: AsyncSession
):
    """Role from a different initiative must be silently dropped."""
    admin = await create_user(session, email="admin@example.com")
    guild = await create_guild(session)
    await create_guild_membership(session, user=admin, guild=guild, role=GuildRole.admin)

    initiative_a = await create_initiative(session, guild, admin, name="Initiative A")
    initiative_b = await create_initiative(session, guild, admin, name="Initiative B")

    # Get a role that belongs to initiative_b, not initiative_a
    result = await session.exec(
        select(InitiativeRoleModel).where(
            InitiativeRoleModel.initiative_id == initiative_b.id,
            InitiativeRoleModel.name == "member",
        )
    )
    foreign_role = result.one()

    headers = get_guild_headers(guild, admin)
    payload = {
        "title": "Doc Cross Initiative",
        "initiative_id": initiative_a.id,
        "role_permissions": [
            {"initiative_role_id": foreign_role.id, "level": "read"},
        ],
    }

    response = await client.post("/api/v1/documents/", headers=headers, json=payload)

    assert response.status_code == 201
    data = response.json()
    # Foreign role must have been silently dropped
    assert len(data["role_permissions"]) == 0


@pytest.mark.integration
async def test_create_document_skips_owner_level_grants(
    client: AsyncClient, session: AsyncSession
):
    """Owner-level grants in user_permissions must be silently ignored."""
    admin = await create_user(session, email="admin@example.com")
    member = await create_user(session, email="member@example.com")
    guild = await create_guild(session)
    await create_guild_membership(session, user=admin, guild=guild, role=GuildRole.admin)
    await create_guild_membership(session, user=member, guild=guild)
    initiative = await create_initiative(session, guild, admin, name="Test Initiative")
    await create_initiative_member(session, initiative, member, role_name="member")

    headers = get_guild_headers(guild, admin)
    payload = {
        "title": "Doc Owner Skip",
        "initiative_id": initiative.id,
        "user_permissions": [{"user_id": member.id, "level": "owner"}],
    }

    response = await client.post("/api/v1/documents/", headers=headers, json=payload)

    assert response.status_code == 201
    member_perms = [p for p in response.json()["permissions"] if p["user_id"] == member.id]
    assert len(member_perms) == 0
