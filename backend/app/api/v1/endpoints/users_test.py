"""
Integration tests for user endpoints.

Tests the user API endpoints at /api/v1/users including:
- Getting current user info
- Listing users in a guild
- Updating user profile
- User deletion
"""

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.guild import GuildRole
from app.models.user import UserRole
from app.testing.factories import (
    create_guild,
    create_guild_membership,
    create_user,
    get_auth_headers,
    get_guild_headers,
)


@pytest.mark.integration
async def test_get_current_user(client: AsyncClient, session: AsyncSession):
    """Test getting current user's profile."""
    user = await create_user(
        session,
        email="test@example.com",
        full_name="Test User",
    )
    headers = get_auth_headers(user)

    response = await client.get("/api/v1/users/me", headers=headers)

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == user.id
    assert data["email"] == "test@example.com"
    assert data["full_name"] == "Test User"
    assert data["is_active"] is True


@pytest.mark.integration
async def test_get_current_user_requires_auth(client: AsyncClient):
    """Test that getting current user requires authentication."""
    response = await client.get("/api/v1/users/me")

    assert response.status_code == 401


@pytest.mark.integration
async def test_update_current_user_profile(client: AsyncClient, session: AsyncSession):
    """Test updating current user's profile."""
    user = await create_user(session, email="test@example.com", full_name="Old Name")
    headers = get_auth_headers(user)

    update_data = {
        "full_name": "New Name",
        "timezone": "America/New_York",
    }

    response = await client.patch("/api/v1/users/me", headers=headers, json=update_data)

    assert response.status_code == 200
    data = response.json()
    assert data["full_name"] == "New Name"
    assert data["timezone"] == "America/New_York"


@pytest.mark.integration
async def test_update_current_user_notification_preferences(
    client: AsyncClient, session: AsyncSession
):
    """Test updating notification preferences."""
    user = await create_user(session)
    headers = get_auth_headers(user)

    update_data = {
        "email_task_assignment": False,
        "email_overdue_tasks": False,
    }

    response = await client.patch("/api/v1/users/me", headers=headers, json=update_data)

    assert response.status_code == 200
    data = response.json()
    assert data["email_task_assignment"] is False
    assert data["email_overdue_tasks"] is False


@pytest.mark.integration
async def test_list_users_in_guild(client: AsyncClient, session: AsyncSession):
    """Test listing users in a guild."""
    guild = await create_guild(session)
    user1 = await create_user(session, email="user1@example.com", full_name="User One")
    user2 = await create_user(session, email="user2@example.com", full_name="User Two")

    await create_guild_membership(session, user=user1, guild=guild)
    await create_guild_membership(session, user=user2, guild=guild)

    headers = get_guild_headers(guild, user1)

    response = await client.get("/api/v1/users/", headers=headers)

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    emails = {user["email"] for user in data}
    assert "user1@example.com" in emails
    assert "user2@example.com" in emails


@pytest.mark.integration
async def test_list_users_requires_guild_context(client: AsyncClient, session: AsyncSession):
    """Test that listing users requires guild context."""
    user = await create_user(session)
    headers = get_auth_headers(user)

    response = await client.get("/api/v1/users/", headers=headers)

    # Should fail without guild membership
    assert response.status_code == 403


@pytest.mark.integration
async def test_update_user_by_id_as_admin(client: AsyncClient, session: AsyncSession):
    """Test that guild admin can update other users."""
    guild = await create_guild(session)
    admin = await create_user(session, email="admin@example.com")
    member = await create_user(session, email="member@example.com", full_name="Old Name")

    await create_guild_membership(session, user=admin, guild=guild, role=GuildRole.admin)
    await create_guild_membership(session, user=member, guild=guild, role=GuildRole.member)

    headers = get_guild_headers(guild, admin)

    update_data = {"full_name": "New Name"}

    response = await client.patch(
        f"/api/v1/users/{member.id}",
        headers=headers,
        json=update_data,
    )

    assert response.status_code == 200
    data = response.json()
    assert data["full_name"] == "New Name"


@pytest.mark.integration
async def test_update_user_as_member_forbidden(client: AsyncClient, session: AsyncSession):
    """Test that regular members cannot update other users."""
    guild = await create_guild(session)
    member1 = await create_user(session, email="member1@example.com")
    member2 = await create_user(session, email="member2@example.com")

    await create_guild_membership(session, user=member1, guild=guild, role=GuildRole.member)
    await create_guild_membership(session, user=member2, guild=guild, role=GuildRole.member)

    headers = get_guild_headers(guild, member1)

    update_data = {"full_name": "Hacked Name"}

    response = await client.patch(
        f"/api/v1/users/{member2.id}",
        headers=headers,
        json=update_data,
    )

    assert response.status_code == 403


@pytest.mark.integration
async def test_check_deletion_eligibility(client: AsyncClient, session: AsyncSession):
    """Test checking if user can delete their account."""
    guild = await create_guild(session)
    admin = await create_user(session, email="admin@example.com")
    member = await create_user(session, email="member@example.com")

    await create_guild_membership(session, user=admin, guild=guild, role=GuildRole.admin)
    await create_guild_membership(session, user=member, guild=guild, role=GuildRole.member)

    headers = get_auth_headers(member)

    response = await client.get("/api/v1/users/me/deletion-eligibility", headers=headers)

    assert response.status_code == 200
    data = response.json()
    assert "can_delete" in data
    assert "blockers" in data
    assert "warnings" in data


@pytest.mark.integration
async def test_delete_user_as_admin(client: AsyncClient, session: AsyncSession):
    """Test that guild admin can delete users."""
    guild = await create_guild(session)
    admin = await create_user(session, email="admin@example.com")
    member = await create_user(session, email="member@example.com")

    await create_guild_membership(session, user=admin, guild=guild, role=GuildRole.admin)
    await create_guild_membership(session, user=member, guild=guild, role=GuildRole.member)

    headers = get_guild_headers(guild, admin)

    response = await client.delete(f"/api/v1/users/{member.id}", headers=headers)

    assert response.status_code == 204


@pytest.mark.integration
async def test_delete_user_as_member_forbidden(client: AsyncClient, session: AsyncSession):
    """Test that regular members cannot delete users."""
    guild = await create_guild(session)
    member1 = await create_user(session, email="member1@example.com")
    member2 = await create_user(session, email="member2@example.com")

    await create_guild_membership(session, user=member1, guild=guild, role=GuildRole.member)
    await create_guild_membership(session, user=member2, guild=guild, role=GuildRole.member)

    headers = get_guild_headers(guild, member1)

    response = await client.delete(f"/api/v1/users/{member2.id}", headers=headers)

    assert response.status_code == 403


@pytest.mark.integration
async def test_user_cannot_update_email_via_patch(client: AsyncClient, session: AsyncSession):
    """Test that users cannot change their email via PATCH /me."""
    user = await create_user(session, email="original@example.com")
    headers = get_auth_headers(user)

    update_data = {"email": "hacked@example.com"}

    response = await client.patch("/api/v1/users/me", headers=headers, json=update_data)

    # Should succeed but email should not change
    assert response.status_code == 200
    data = response.json()
    assert data["email"] == "original@example.com"


@pytest.mark.integration
async def test_user_can_change_password(client: AsyncClient, session: AsyncSession):
    """Test that users can change their password."""
    user = await create_user(session, email="test@example.com")
    headers = get_auth_headers(user)

    update_data = {"password": "newpassword123"}

    response = await client.patch("/api/v1/users/me", headers=headers, json=update_data)

    assert response.status_code == 200

    # TODO: Verify password actually changed by trying to login with new password


@pytest.mark.integration
async def test_inactive_user_cannot_access_endpoints(client: AsyncClient, session: AsyncSession):
    """Test that inactive users cannot access protected endpoints."""
    from app.models.user import User

    # Create inactive user
    user = User(
        email="inactive@example.com",
        full_name="Inactive User",
        hashed_password="dummy",
        is_active=False,
    )
    session.add(user)
    await session.commit()

    headers = get_auth_headers(user)

    response = await client.get("/api/v1/users/me", headers=headers)

    # Should be rejected because user is inactive
    assert response.status_code == 400
    assert "inactive" in response.json()["detail"].lower()


@pytest.mark.integration
async def test_user_timezone_validation(client: AsyncClient, session: AsyncSession):
    """Test that invalid timezones are rejected."""
    user = await create_user(session)
    headers = get_auth_headers(user)

    update_data = {"timezone": "Invalid/Timezone"}

    response = await client.patch("/api/v1/users/me", headers=headers, json=update_data)

    assert response.status_code == 400
    assert "timezone" in response.json()["detail"].lower()


@pytest.mark.integration
async def test_user_week_starts_on_validation(client: AsyncClient, session: AsyncSession):
    """Test that week_starts_on only accepts 0-6."""
    user = await create_user(session)
    headers = get_auth_headers(user)

    # Invalid value (7)
    update_data = {"week_starts_on": 7}

    response = await client.patch("/api/v1/users/me", headers=headers, json=update_data)

    assert response.status_code in [400, 422]  # Validation error


@pytest.mark.integration
async def test_list_users_only_shows_guild_members(client: AsyncClient, session: AsyncSession):
    """Test that listing users only shows members of the current guild."""
    guild1 = await create_guild(session, name="Guild 1")
    guild2 = await create_guild(session, name="Guild 2")

    user1 = await create_user(session, email="user1@example.com")
    user2 = await create_user(session, email="user2@example.com")

    await create_guild_membership(session, user=user1, guild=guild1)
    await create_guild_membership(session, user=user2, guild=guild2)

    headers = get_guild_headers(guild1, user1)

    response = await client.get("/api/v1/users/", headers=headers)

    assert response.status_code == 200
    data = response.json()
    # Should only see user1, not user2
    assert len(data) == 1
    assert data[0]["email"] == "user1@example.com"
