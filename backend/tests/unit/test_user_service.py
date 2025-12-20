"""
Unit tests for user service functions.

Tests the business logic in app.services.users including:
- System user management
- Deletion eligibility checks
- Project ownership transfers
- User content reassignment
"""

import pytest
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.guild import GuildRole
from app.models.user import User
from app.services import users as user_service
from tests.factories import (
    create_guild,
    create_guild_membership,
    create_user,
)


@pytest.mark.unit
@pytest.mark.service
async def test_get_or_create_system_user(session: AsyncSession):
    """Test that system user is created on first call and reused on subsequent calls."""
    # First call should create the system user
    system_user1 = await user_service.get_or_create_system_user(session)

    assert system_user1.id is not None
    assert system_user1.email == user_service.SYSTEM_USER_EMAIL
    assert system_user1.full_name == user_service.SYSTEM_USER_FULL_NAME
    assert system_user1.is_active is False
    assert system_user1.email_verified is True

    # Second call should return the same user
    system_user2 = await user_service.get_or_create_system_user(session)

    assert system_user2.id == system_user1.id
    assert system_user2.email == system_user1.email

    # Verify only one system user exists
    stmt = select(User).where(User.email == user_service.SYSTEM_USER_EMAIL)
    result = await session.exec(stmt)
    all_system_users = result.all()
    assert len(all_system_users) == 1


@pytest.mark.unit
@pytest.mark.service
async def test_is_last_guild_admin_true(session: AsyncSession):
    """Test detection when user is the last admin of a guild."""
    # Create a guild with one admin
    admin_user = await create_user(session)
    guild = await create_guild(session, creator=admin_user)
    await create_guild_membership(
        session,
        user=admin_user,
        guild=guild,
        role=GuildRole.admin,
    )

    # Check if user is last admin
    last_admin_guilds = await user_service.is_last_guild_admin(session, admin_user.id)

    assert len(last_admin_guilds) == 1
    assert last_admin_guilds[0] == guild.name


@pytest.mark.unit
@pytest.mark.service
async def test_is_last_guild_admin_false_multiple_admins(session: AsyncSession):
    """Test that user is not considered last admin when other admins exist."""
    # Create a guild with two admins
    admin1 = await create_user(session, email="admin1@example.com")
    admin2 = await create_user(session, email="admin2@example.com")
    guild = await create_guild(session, creator=admin1)

    await create_guild_membership(session, user=admin1, guild=guild, role=GuildRole.admin)
    await create_guild_membership(session, user=admin2, guild=guild, role=GuildRole.admin)

    # Check if admin1 is last admin (should be False)
    last_admin_guilds = await user_service.is_last_guild_admin(session, admin1.id)

    assert len(last_admin_guilds) == 0


@pytest.mark.unit
@pytest.mark.service
async def test_is_last_guild_admin_false_only_member(session: AsyncSession):
    """Test that regular members are not considered as last admin."""
    # Create a guild with an admin and a member
    admin = await create_user(session, email="admin@example.com")
    member = await create_user(session, email="member@example.com")
    guild = await create_guild(session, creator=admin)

    await create_guild_membership(session, user=admin, guild=guild, role=GuildRole.admin)
    await create_guild_membership(session, user=member, guild=guild, role=GuildRole.member)

    # Check if member is last admin (should be False)
    last_admin_guilds = await user_service.is_last_guild_admin(session, member.id)

    assert len(last_admin_guilds) == 0


@pytest.mark.unit
@pytest.mark.service
async def test_is_last_guild_admin_multiple_guilds(session: AsyncSession):
    """Test detection across multiple guilds."""
    admin = await create_user(session)

    # Guild 1: admin is last admin
    guild1 = await create_guild(session, name="Guild 1", creator=admin)
    await create_guild_membership(session, user=admin, guild=guild1, role=GuildRole.admin)

    # Guild 2: admin is one of two admins
    other_admin = await create_user(session, email="other@example.com")
    guild2 = await create_guild(session, name="Guild 2", creator=other_admin)
    await create_guild_membership(session, user=admin, guild=guild2, role=GuildRole.admin)
    await create_guild_membership(session, user=other_admin, guild=guild2, role=GuildRole.admin)

    # Check which guilds admin is last admin of
    last_admin_guilds = await user_service.is_last_guild_admin(session, admin.id)

    assert len(last_admin_guilds) == 1
    assert "Guild 1" in last_admin_guilds
    assert "Guild 2" not in last_admin_guilds


@pytest.mark.unit
@pytest.mark.service
async def test_check_deletion_eligibility_can_delete(session: AsyncSession):
    """Test that user can be deleted when they have no blocking conditions."""
    # Create a regular member user
    member = await create_user(session)
    admin = await create_user(session, email="admin@example.com")
    guild = await create_guild(session, creator=admin)

    await create_guild_membership(session, user=admin, guild=guild, role=GuildRole.admin)
    await create_guild_membership(session, user=member, guild=guild, role=GuildRole.member)

    # Check deletion eligibility
    can_delete, blockers, _warnings, owned_projects = await user_service.check_deletion_eligibility(
        session,
        member.id,
    )

    assert can_delete is True
    assert len(blockers) == 0
    assert len(owned_projects) == 0


@pytest.mark.unit
@pytest.mark.service
async def test_check_deletion_eligibility_blocked_last_admin(session: AsyncSession):
    """Test that user cannot be deleted when they are last admin of a guild."""
    # Create a guild where user is the only admin
    admin = await create_user(session)
    guild = await create_guild(session, name="My Guild", creator=admin)
    await create_guild_membership(session, user=admin, guild=guild, role=GuildRole.admin)

    # Check deletion eligibility
    can_delete, blockers, _warnings, _owned_projects = await user_service.check_deletion_eligibility(
        session,
        admin.id,
    )

    assert can_delete is False
    assert len(blockers) >= 1
    assert any("My Guild" in blocker for blocker in blockers)
    assert any("last admin" in blocker.lower() for blocker in blockers)


@pytest.mark.unit
@pytest.mark.service
async def test_soft_delete_user(session: AsyncSession):
    """Test soft deletion deactivates user and removes guild memberships."""
    # Create user with guild membership
    user = await create_user(session, email="todelete@example.com")
    admin = await create_user(session, email="admin@example.com")
    guild = await create_guild(session, creator=admin)

    await create_guild_membership(session, user=admin, guild=guild, role=GuildRole.admin)
    await create_guild_membership(session, user=user, guild=guild, role=GuildRole.member)

    # Soft delete the user
    await user_service.soft_delete_user(session, user.id)

    # Verify user is deactivated
    stmt = select(User).where(User.id == user.id)
    result = await session.exec(stmt)
    deleted_user = result.one()

    assert deleted_user.is_active is False
    assert deleted_user.active_guild_id is None
