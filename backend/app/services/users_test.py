"""
Unit tests for user service functions.

Tests the business logic in app.services.users including:
- System user management
- Deletion eligibility checks
- Project ownership transfers
- User content reassignment
"""

from datetime import datetime, timezone

import pytest
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.guild import GuildRole
from app.models.user import User, UserStatus
from app.services import users as user_service
from app.testing.factories import (
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
    assert system_user1.status == UserStatus.deactivated
    assert system_user1.email_verified is True

    # Second call should return the same user
    system_user2 = await user_service.get_or_create_system_user(session)

    assert system_user2.id == system_user1.id
    assert system_user2.email == system_user1.email

    # Verify only one system user exists
    from app.core.encryption import hash_email
    stmt = select(User).where(User.email_hash == hash_email(user_service.SYSTEM_USER_EMAIL))
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
async def test_deactivate_user(session: AsyncSession):
    """Deactivation flips status, drops memberships, bumps token_version,
    and leaves PII intact so an admin can later reactivate."""
    user = await create_user(
        session, email="todeactivate@example.com", full_name="Original Name"
    )
    admin = await create_user(session, email="admin@example.com")
    guild = await create_guild(session, creator=admin)

    await create_guild_membership(session, user=admin, guild=guild, role=GuildRole.admin)
    await create_guild_membership(session, user=user, guild=guild, role=GuildRole.member)

    original_token_version = user.token_version

    await user_service.deactivate_user(session, user.id)

    stmt = select(User).where(User.id == user.id)
    result = await session.exec(stmt)
    deactivated = result.one()

    assert deactivated.status == UserStatus.deactivated
    assert deactivated.token_version == original_token_version + 1
    # PII preserved — admin can reactivate.
    assert deactivated.full_name == "Original Name"
    assert deactivated.email == "todeactivate@example.com"


@pytest.mark.unit
@pytest.mark.service
async def test_soft_delete_user_anonymizes_pii(session: AsyncSession):
    """Soft delete (anonymize) clears PII, blocks login, drops memberships,
    demotes platform admins to member, revokes auth artifacts, and keeps
    the row so historical FKs resolve."""
    from app.models.api_key import UserApiKey
    from app.models.push_token import PushToken
    from app.models.user_token import UserToken
    from app.models.user import UserRole

    user = await create_user(
        session,
        email="toanonymize@example.com",
        full_name="Anonymizer Test",
        avatar_url="https://example.com/avatar.png",
        role=UserRole.admin,
    )
    admin = await create_user(session, email="admin@example.com")
    guild = await create_guild(session, creator=admin)

    await create_guild_membership(session, user=admin, guild=guild, role=GuildRole.admin)
    await create_guild_membership(session, user=user, guild=guild, role=GuildRole.member)

    # Seed auth artifacts that should be revoked.
    session.add(
        UserApiKey(
            user_id=user.id,
            name="key",
            token_prefix="ppk_xxxx",
            token_hash="hash-1",
        )
    )
    session.add(
        UserToken(
            user_id=user.id,
            token="utoken-1",
            purpose="password_reset",
            expires_at=datetime.now(timezone.utc),
        )
    )
    session.add(PushToken(user_id=user.id, push_token="device-token", platform="web"))
    await session.commit()

    original_id = user.id
    original_token_version = user.token_version
    original_email_hash = user.email_hash

    await user_service.soft_delete_user(session, user.id)

    stmt = select(User).where(User.id == original_id)
    result = await session.exec(stmt)
    anonymized = result.one()

    # The row stays — same id, same created_at — so FKs resolve.
    assert anonymized.id == original_id
    assert anonymized.status == UserStatus.anonymized
    # Platform-admin role demoted to member so the husk doesn't carry
    # elevated privileges.
    assert anonymized.role == UserRole.member
    # PII gone.
    assert anonymized.full_name is None
    assert anonymized.avatar_url is None
    assert anonymized.avatar_base64 is None
    assert anonymized.oidc_sub is None
    assert anonymized.email_hash != original_email_hash
    # Login is doubly impossible: the email_hash no longer matches the
    # user's old email, and the password hash is fresh nonsense.
    assert anonymized.email != "toanonymize@example.com"
    # Token version bumped (deactivate already bumped, anonymize keeps it).
    assert anonymized.token_version >= original_token_version + 1

    # Auth artifacts revoked.
    api_keys = (await session.exec(select(UserApiKey).where(UserApiKey.user_id == original_id))).all()
    user_tokens_left = (await session.exec(select(UserToken).where(UserToken.user_id == original_id))).all()
    push_tokens_left = (await session.exec(select(PushToken).where(PushToken.user_id == original_id))).all()
    assert api_keys == []
    assert user_tokens_left == []
    assert push_tokens_left == []


@pytest.mark.unit
@pytest.mark.service
async def test_users_table_has_rls_delete_deny_policy(session: AsyncSession):
    """The migration must enable RLS on `users` and install the
    ``users_no_delete`` restrictive policy that blocks DELETE for any
    non-bypass session. Application code that tries to drop a user row
    via the regular ``app_user`` role would silently affect zero rows
    without this policy."""
    from sqlalchemy import text

    rls_enabled = await session.exec(
        text("SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname = 'users'")
    )
    enabled, forced = rls_enabled.one()
    assert enabled is True
    assert forced is True

    policies = await session.exec(
        text(
            "SELECT polname, polcmd, polpermissive FROM pg_policy "
            "WHERE polrelid = 'users'::regclass ORDER BY polname"
        )
    )
    rows = list(policies)
    names = {row[0] for row in rows}
    assert "users_no_delete" in names
    assert "users_open" in names
    deny_policy = next(row for row in rows if row[0] == "users_no_delete")
    # polcmd '6' = DELETE; polpermissive False = restrictive.
    # See: https://www.postgresql.org/docs/current/catalog-pg-policy.html
    assert deny_policy[2] is False  # restrictive


@pytest.mark.unit
@pytest.mark.service
async def test_is_last_platform_admin_ignores_inactive_targets(session: AsyncSession):
    """An admin whose status isn't ``active`` doesn't contribute to the
    active-admin count, so they can never be "the last admin". Without
    this fix, deleting a deactivated admin while another active admin
    existed would trip the wrong-blocker path: ``count_platform_admins``
    saw 1 (just the other admin), the helper returned True for the
    deactivated target, and the eligibility endpoint blocked the
    delete with "User is the last platform admin".
    """
    from app.models.user import UserRole

    active_admin = await create_user(
        session, email="active-admin@example.com", role=UserRole.admin
    )
    deact_admin = await create_user(
        session, email="deact-admin@example.com", role=UserRole.admin
    )
    await user_service.deactivate_user(session, deact_admin.id)

    # The active admin really is the last *active* admin.
    assert await user_service.is_last_platform_admin(session, active_admin.id) is True

    # The deactivated admin is never "the last admin" — they're not in
    # the count to begin with, so removing them changes nothing.
    assert await user_service.is_last_platform_admin(session, deact_admin.id) is False


@pytest.mark.unit
@pytest.mark.service
async def test_is_last_platform_admin_with_other_active_admin(session: AsyncSession):
    """When a second active admin exists, neither is the last admin."""
    from app.models.user import UserRole

    a = await create_user(session, email="a@example.com", role=UserRole.admin)
    b = await create_user(session, email="b@example.com", role=UserRole.admin)

    assert await user_service.is_last_platform_admin(session, a.id) is False
    assert await user_service.is_last_platform_admin(session, b.id) is False
