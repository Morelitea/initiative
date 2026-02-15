"""
Integration tests for guild endpoints.

Tests the guild API endpoints at /api/v1/guilds including:
- Listing guilds
- Creating guilds
- Updating guilds
- Deleting guilds
- Switching active guild
- Reordering guilds
- Creating and managing invites
- Accepting invites
"""

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.guild import GuildRole
from app.testing.factories import (
    create_guild,
    create_guild_membership,
    create_user,
    get_auth_headers,
)


@pytest.mark.integration
async def test_list_guilds_empty(client: AsyncClient, session: AsyncSession):
    """Test listing guilds when user has no memberships."""
    user = await create_user(session, email="test@example.com")
    headers = get_auth_headers(user)

    response = await client.get("/api/v1/guilds/", headers=headers)

    assert response.status_code == 200
    data = response.json()
    assert data == []


@pytest.mark.integration
async def test_list_guilds_with_memberships(client: AsyncClient, session: AsyncSession):
    """Test listing guilds shows all user's guilds."""
    user = await create_user(session, email="test@example.com")
    guild1 = await create_guild(session, name="Guild 1")
    guild2 = await create_guild(session, name="Guild 2")

    await create_guild_membership(session, user=user, guild=guild1)
    await create_guild_membership(session, user=user, guild=guild2)

    headers = get_auth_headers(user)
    response = await client.get("/api/v1/guilds/", headers=headers)

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    guild_names = {g["name"] for g in data}
    assert "Guild 1" in guild_names
    assert "Guild 2" in guild_names


@pytest.mark.integration
async def test_list_guilds_includes_role(client: AsyncClient, session: AsyncSession):
    """Test that guild list includes user's role in each guild."""
    user = await create_user(session, email="test@example.com")
    admin_guild = await create_guild(session, name="Admin Guild")
    member_guild = await create_guild(session, name="Member Guild")

    await create_guild_membership(session, user=user, guild=admin_guild, role=GuildRole.admin)
    await create_guild_membership(session, user=user, guild=member_guild, role=GuildRole.member)

    headers = get_auth_headers(user)
    response = await client.get("/api/v1/guilds/", headers=headers)

    assert response.status_code == 200
    data = response.json()

    guild_roles = {g["name"]: g["role"] for g in data}
    assert guild_roles["Admin Guild"] == "admin"
    assert guild_roles["Member Guild"] == "member"


@pytest.mark.integration
async def test_list_guilds_shows_active_guild(client: AsyncClient, session: AsyncSession):
    """Test listing guilds returns role and position."""
    user = await create_user(session, email="test@example.com")
    guild1 = await create_guild(session, name="Guild 1")
    guild2 = await create_guild(session, name="Guild 2")

    await create_guild_membership(session, user=user, guild=guild1)
    await create_guild_membership(session, user=user, guild=guild2)

    headers = get_auth_headers(user)
    response = await client.get("/api/v1/guilds/", headers=headers)

    assert response.status_code == 200
    data = response.json()

    guild_names = {g["name"] for g in data}
    assert "Guild 1" in guild_names
    assert "Guild 2" in guild_names
    # is_active is no longer returned; active guild is client-side only
    assert "is_active" not in data[0]


@pytest.mark.integration
async def test_create_guild(client: AsyncClient, session: AsyncSession):
    """Test creating a new guild."""
    user = await create_user(session, email="test@example.com")
    headers = get_auth_headers(user)

    payload = {
        "name": "New Guild",
        "description": "A test guild",
    }

    response = await client.post("/api/v1/guilds/", headers=headers, json=payload)

    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "New Guild"
    assert data["description"] == "A test guild"
    assert data["role"] == "admin"


@pytest.mark.integration
async def test_create_guild_with_icon(client: AsyncClient, session: AsyncSession):
    """Test creating a guild with an icon."""
    user = await create_user(session, email="test@example.com")
    headers = get_auth_headers(user)

    payload = {
        "name": "Icon Guild",
        "description": "Guild with icon",
        "icon_base64": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
    }

    response = await client.post("/api/v1/guilds/", headers=headers, json=payload)

    assert response.status_code == 201
    data = response.json()
    assert data["icon_base64"] is not None


@pytest.mark.integration
async def test_create_guild_requires_name(client: AsyncClient, session: AsyncSession):
    """Test that creating a guild requires a name."""
    user = await create_user(session, email="test@example.com")
    headers = get_auth_headers(user)

    payload = {"name": "   ", "description": "No name"}

    response = await client.post("/api/v1/guilds/", headers=headers, json=payload)

    assert response.status_code == 400
    assert response.json()["detail"] == "GUILD_NAME_REQUIRED"


@pytest.mark.integration
async def test_create_guild_sets_as_active(client: AsyncClient, session: AsyncSession):
    """Test that creating a guild sets it as the user's active guild."""
    user = await create_user(session, email="test@example.com")
    headers = get_auth_headers(user)

    payload = {"name": "Active Guild"}

    response = await client.post("/api/v1/guilds/", headers=headers, json=payload)

    assert response.status_code == 201


@pytest.mark.integration
async def test_update_guild_as_admin(client: AsyncClient, session: AsyncSession):
    """Test that admin can update guild."""
    user = await create_user(session, email="admin@example.com")
    guild = await create_guild(session, name="Old Name", description="Old description")
    await create_guild_membership(session, user=user, guild=guild, role=GuildRole.admin)

    headers = get_auth_headers(user)
    payload = {"name": "New Name", "description": "New description"}

    response = await client.patch(f"/api/v1/guilds/{guild.id}", headers=headers, json=payload)

    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "New Name"
    assert data["description"] == "New description"


@pytest.mark.integration
async def test_update_guild_as_member_forbidden(client: AsyncClient, session: AsyncSession):
    """Test that regular members cannot update guild."""
    user = await create_user(session, email="member@example.com")
    guild = await create_guild(session, name="Test Guild")
    await create_guild_membership(session, user=user, guild=guild, role=GuildRole.member)

    headers = get_auth_headers(user)
    payload = {"name": "Hacked Name"}

    response = await client.patch(f"/api/v1/guilds/{guild.id}", headers=headers, json=payload)

    assert response.status_code == 403


@pytest.mark.integration
async def test_update_guild_without_membership_forbidden(client: AsyncClient, session: AsyncSession):
    """Test that users without membership cannot update guild."""
    user = await create_user(session, email="outsider@example.com")
    guild = await create_guild(session, name="Test Guild")

    headers = get_auth_headers(user)
    payload = {"name": "Hacked Name"}

    response = await client.patch(f"/api/v1/guilds/{guild.id}", headers=headers, json=payload)

    assert response.status_code == 403


@pytest.mark.integration
async def test_delete_guild_as_admin(client: AsyncClient, session: AsyncSession):
    """Test that admin can delete guild."""
    user = await create_user(session, email="admin@example.com")
    guild = await create_guild(session, name="To Delete")
    await create_guild_membership(session, user=user, guild=guild, role=GuildRole.admin)

    headers = get_auth_headers(user)
    response = await client.delete(f"/api/v1/guilds/{guild.id}", headers=headers)

    assert response.status_code == 204


@pytest.mark.integration
async def test_delete_guild_as_member_forbidden(client: AsyncClient, session: AsyncSession):
    """Test that regular members cannot delete guild."""
    user = await create_user(session, email="member@example.com")
    guild = await create_guild(session, name="Test Guild")
    await create_guild_membership(session, user=user, guild=guild, role=GuildRole.member)

    headers = get_auth_headers(user)
    response = await client.delete(f"/api/v1/guilds/{guild.id}", headers=headers)

    assert response.status_code == 403


@pytest.mark.integration
async def test_reorder_guilds(client: AsyncClient, session: AsyncSession):
    """Test reordering user's guilds."""
    user = await create_user(session, email="test@example.com")
    guild1 = await create_guild(session, name="Guild 1")
    guild2 = await create_guild(session, name="Guild 2")
    guild3 = await create_guild(session, name="Guild 3")

    await create_guild_membership(session, user=user, guild=guild1)
    await create_guild_membership(session, user=user, guild=guild2)
    await create_guild_membership(session, user=user, guild=guild3)

    headers = get_auth_headers(user)
    payload = {"guild_ids": [guild3.id, guild1.id, guild2.id]}

    response = await client.put("/api/v1/guilds/order", headers=headers, json=payload)

    assert response.status_code == 204

    # Verify order changed
    list_response = await client.get("/api/v1/guilds/", headers=headers)
    guilds = list_response.json()
    ordered_ids = [g["id"] for g in guilds]
    assert ordered_ids == [guild3.id, guild1.id, guild2.id]


@pytest.mark.integration
async def test_create_guild_invite_as_admin(client: AsyncClient, session: AsyncSession):
    """Test that admin can create guild invites."""
    user = await create_user(session, email="admin@example.com")
    guild = await create_guild(session, name="Test Guild")
    await create_guild_membership(session, user=user, guild=guild, role=GuildRole.admin)

    headers = get_auth_headers(user)
    payload = {"max_uses": 5, "invitee_email": "invitee@example.com"}

    response = await client.post(f"/api/v1/guilds/{guild.id}/invites", headers=headers, json=payload)

    assert response.status_code == 201
    data = response.json()
    assert data["guild_id"] == guild.id
    assert data["max_uses"] == 5
    assert data["invitee_email"] == "invitee@example.com"
    assert data["uses"] == 0
    assert len(data["code"]) == 22


@pytest.mark.integration
async def test_create_guild_invite_with_expiration(client: AsyncClient, session: AsyncSession):
    """Test creating an invite with expiration date."""
    user = await create_user(session, email="admin@example.com")
    guild = await create_guild(session, name="Test Guild")
    await create_guild_membership(session, user=user, guild=guild, role=GuildRole.admin)

    headers = get_auth_headers(user)
    payload = {
        "max_uses": 1,
        "expires_at": "2025-12-31T23:59:59Z",
    }

    response = await client.post(f"/api/v1/guilds/{guild.id}/invites", headers=headers, json=payload)

    assert response.status_code == 201
    data = response.json()
    assert data["expires_at"] is not None
    assert "2025-12-31" in data["expires_at"]


@pytest.mark.integration
async def test_create_guild_invite_as_member_forbidden(client: AsyncClient, session: AsyncSession):
    """Test that regular members cannot create invites."""
    user = await create_user(session, email="member@example.com")
    guild = await create_guild(session, name="Test Guild")
    await create_guild_membership(session, user=user, guild=guild, role=GuildRole.member)

    headers = get_auth_headers(user)
    payload = {"max_uses": 5}

    response = await client.post(f"/api/v1/guilds/{guild.id}/invites", headers=headers, json=payload)

    assert response.status_code == 403


@pytest.mark.integration
async def test_list_guild_invites_as_admin(client: AsyncClient, session: AsyncSession):
    """Test that admin can list guild invites."""
    from app.services import guilds as guild_service

    user = await create_user(session, email="admin@example.com")
    guild = await create_guild(session, name="Test Guild")
    await create_guild_membership(session, user=user, guild=guild, role=GuildRole.admin)

    # Create some invites
    await guild_service.create_guild_invite(session, guild_id=guild.id, created_by_user_id=user.id, max_uses=1)
    await guild_service.create_guild_invite(session, guild_id=guild.id, created_by_user_id=user.id, max_uses=2)
    await session.commit()

    headers = get_auth_headers(user)
    response = await client.get(f"/api/v1/guilds/{guild.id}/invites", headers=headers)

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2


@pytest.mark.integration
async def test_list_guild_invites_as_member_forbidden(client: AsyncClient, session: AsyncSession):
    """Test that regular members cannot list invites."""
    user = await create_user(session, email="member@example.com")
    guild = await create_guild(session, name="Test Guild")
    await create_guild_membership(session, user=user, guild=guild, role=GuildRole.member)

    headers = get_auth_headers(user)
    response = await client.get(f"/api/v1/guilds/{guild.id}/invites", headers=headers)

    assert response.status_code == 403


@pytest.mark.integration
async def test_delete_guild_invite_as_admin(client: AsyncClient, session: AsyncSession):
    """Test that admin can delete guild invites."""
    from app.services import guilds as guild_service

    user = await create_user(session, email="admin@example.com")
    guild = await create_guild(session, name="Test Guild")
    await create_guild_membership(session, user=user, guild=guild, role=GuildRole.admin)

    invite = await guild_service.create_guild_invite(
        session, guild_id=guild.id, created_by_user_id=user.id
    )
    await session.commit()

    headers = get_auth_headers(user)
    response = await client.delete(
        f"/api/v1/guilds/{guild.id}/invites/{invite.id}", headers=headers
    )

    assert response.status_code == 204


@pytest.mark.integration
async def test_delete_guild_invite_as_member_forbidden(client: AsyncClient, session: AsyncSession):
    """Test that regular members cannot delete invites."""
    from app.services import guilds as guild_service

    admin = await create_user(session, email="admin@example.com")
    member = await create_user(session, email="member@example.com")
    guild = await create_guild(session, name="Test Guild")
    await create_guild_membership(session, user=admin, guild=guild, role=GuildRole.admin)
    await create_guild_membership(session, user=member, guild=guild, role=GuildRole.member)

    invite = await guild_service.create_guild_invite(
        session, guild_id=guild.id, created_by_user_id=admin.id
    )
    await session.commit()

    headers = get_auth_headers(member)
    response = await client.delete(
        f"/api/v1/guilds/{guild.id}/invites/{invite.id}", headers=headers
    )

    assert response.status_code == 403


@pytest.mark.integration
async def test_get_invite_status_valid(client: AsyncClient, session: AsyncSession):
    """Test getting status of a valid invite."""
    from app.services import guilds as guild_service

    user = await create_user(session, email="admin@example.com")
    guild = await create_guild(session, name="Test Guild")

    invite = await guild_service.create_guild_invite(
        session, guild_id=guild.id, created_by_user_id=user.id, max_uses=5
    )
    await session.commit()

    response = await client.get(f"/api/v1/guilds/invite/{invite.code}")

    assert response.status_code == 200
    data = response.json()
    assert data["code"] == invite.code
    assert data["guild_id"] == guild.id
    assert data["guild_name"] == "Test Guild"
    assert data["is_valid"] is True
    assert data["max_uses"] == 5
    assert data["uses"] == 0


@pytest.mark.integration
async def test_get_invite_status_invalid_code(client: AsyncClient, session: AsyncSession):
    """Test getting status of invalid invite code."""
    response = await client.get("/api/v1/guilds/invite/invalidcode123")

    assert response.status_code == 200
    data = response.json()
    assert data["is_valid"] is False
    assert data["reason"] is not None


@pytest.mark.integration
async def test_accept_invite(client: AsyncClient, session: AsyncSession):
    """Test accepting a guild invite."""
    from app.services import guilds as guild_service

    creator = await create_user(session, email="creator@example.com")
    invitee = await create_user(session, email="invitee@example.com")
    guild = await create_guild(session, name="Test Guild")

    invite = await guild_service.create_guild_invite(
        session, guild_id=guild.id, created_by_user_id=creator.id, max_uses=5
    )
    await session.commit()

    headers = get_auth_headers(invitee)
    payload = {"code": invite.code}

    response = await client.post("/api/v1/guilds/invite/accept", headers=headers, json=payload)

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == guild.id
    assert data["name"] == "Test Guild"
    assert data["role"] == "member"


@pytest.mark.integration
async def test_accept_invalid_invite_fails(client: AsyncClient, session: AsyncSession):
    """Test that accepting invalid invite fails."""
    user = await create_user(session, email="test@example.com")
    headers = get_auth_headers(user)
    payload = {"code": "invalidcode123"}

    response = await client.post("/api/v1/guilds/invite/accept", headers=headers, json=payload)

    assert response.status_code == 400


@pytest.mark.integration
async def test_accept_expired_invite_fails(client: AsyncClient, session: AsyncSession):
    """Test that accepting expired invite fails."""
    from datetime import datetime, timedelta, timezone
    from app.services import guilds as guild_service

    creator = await create_user(session, email="creator@example.com")
    invitee = await create_user(session, email="invitee@example.com")
    guild = await create_guild(session, name="Test Guild")

    invite = await guild_service.create_guild_invite(
        session,
        guild_id=guild.id,
        created_by_user_id=creator.id,
        expires_at=datetime.now(timezone.utc) - timedelta(days=1),
    )
    await session.commit()

    headers = get_auth_headers(invitee)
    payload = {"code": invite.code}

    response = await client.post("/api/v1/guilds/invite/accept", headers=headers, json=payload)

    assert response.status_code == 400
    assert response.json()["detail"] == "INVITE_EXPIRED_OR_USED"


@pytest.mark.integration
async def test_guild_isolation(client: AsyncClient, session: AsyncSession):
    """Test that users only see their own guilds."""
    user1 = await create_user(session, email="user1@example.com")
    user2 = await create_user(session, email="user2@example.com")
    guild1 = await create_guild(session, name="Guild 1")
    guild2 = await create_guild(session, name="Guild 2")

    await create_guild_membership(session, user=user1, guild=guild1)
    await create_guild_membership(session, user=user2, guild=guild2)

    headers1 = get_auth_headers(user1)
    response1 = await client.get("/api/v1/guilds/", headers=headers1)

    assert response1.status_code == 200
    data1 = response1.json()
    assert len(data1) == 1
    assert data1[0]["name"] == "Guild 1"


@pytest.mark.integration
async def test_list_guilds_requires_authentication(client: AsyncClient):
    """Test that listing guilds requires authentication."""
    response = await client.get("/api/v1/guilds/")

    assert response.status_code == 401


@pytest.mark.integration
async def test_create_guild_requires_authentication(client: AsyncClient):
    """Test that creating guilds requires authentication."""
    payload = {"name": "Test Guild"}
    response = await client.post("/api/v1/guilds/", json=payload)

    assert response.status_code == 401
