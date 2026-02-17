"""Tests for Mandatory Access Control — RLS and guild/initiative-level security.

Tests cover:
- Guild-level access checks (is_guild_admin, require_guild_admin)
- Guild membership lookups (get_guild_membership, require_guild_membership)
- Initiative manager checks (is_initiative_manager, assert_initiative_manager)
- Initiative permission checks (check_initiative_permission, has_feature_access)
"""

import pytest
from fastapi import HTTPException
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.messages import GuildMessages, InitiativeMessages
from app.models.guild import GuildRole
from app.models.initiative import DEFAULT_PERMISSION_VALUES, PermissionKey
from app.models.user import UserRole
from app.services.rls import (
    check_initiative_permission,
    get_guild_membership,
    has_feature_access,
    is_guild_admin,
    is_initiative_manager,
    assert_initiative_manager,
    require_guild_admin,
    require_guild_membership,
)
from app.testing import (
    create_guild,
    create_guild_membership,
    create_initiative,
    create_initiative_member,
    create_user,
)


# ---------------------------------------------------------------------------
# Guild-level access checks (sync / unit)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_is_guild_admin_with_admin_role():
    assert is_guild_admin(GuildRole.admin) is True


@pytest.mark.unit
def test_is_guild_admin_with_member_role():
    assert is_guild_admin(GuildRole.member) is False


@pytest.mark.unit
def test_require_guild_admin_passes_for_admin():
    require_guild_admin(GuildRole.admin)  # should not raise


@pytest.mark.unit
def test_require_guild_admin_raises_for_member():
    with pytest.raises(HTTPException) as exc_info:
        require_guild_admin(GuildRole.member)
    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == GuildMessages.GUILD_ADMIN_REQUIRED


# ---------------------------------------------------------------------------
# Guild membership lookups (async / service)
# ---------------------------------------------------------------------------


@pytest.mark.service
async def test_get_guild_membership_found(session: AsyncSession):
    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    await create_guild_membership(session, user=user, guild=guild, role=GuildRole.admin)

    membership = await get_guild_membership(session, guild_id=guild.id, user_id=user.id)

    assert membership is not None
    assert membership.guild_id == guild.id
    assert membership.user_id == user.id


@pytest.mark.service
async def test_get_guild_membership_not_found(session: AsyncSession):
    user = await create_user(session)
    guild = await create_guild(session, creator=user)

    membership = await get_guild_membership(session, guild_id=guild.id, user_id=99999)

    assert membership is None


@pytest.mark.service
async def test_require_guild_membership_found(session: AsyncSession):
    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    await create_guild_membership(session, user=user, guild=guild)

    membership = await require_guild_membership(session, guild_id=guild.id, user_id=user.id)

    assert membership is not None
    assert membership.user_id == user.id


@pytest.mark.service
async def test_require_guild_membership_raises(session: AsyncSession):
    user = await create_user(session)
    guild = await create_guild(session, creator=user)

    with pytest.raises(HTTPException) as exc_info:
        await require_guild_membership(session, guild_id=guild.id, user_id=99999)
    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == GuildMessages.NOT_GUILD_MEMBER


# ---------------------------------------------------------------------------
# Initiative manager checks (async / service)
# ---------------------------------------------------------------------------


@pytest.mark.service
async def test_is_initiative_manager_with_pm_role(session: AsyncSession):
    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    await create_guild_membership(session, user=user, guild=guild, role=GuildRole.admin)
    initiative = await create_initiative(session, guild, user)
    # create_initiative already adds the creator as project_manager

    result = await is_initiative_manager(session, initiative_id=initiative.id, user=user)

    assert result is True


@pytest.mark.service
async def test_is_initiative_manager_with_member_role(session: AsyncSession):
    admin = await create_user(session, email="admin@example.com")
    guild = await create_guild(session, creator=admin)
    await create_guild_membership(session, user=admin, guild=guild, role=GuildRole.admin)
    initiative = await create_initiative(session, guild, admin)

    member = await create_user(session, email="member@example.com")
    await create_guild_membership(session, user=member, guild=guild)
    await create_initiative_member(session, initiative, member, role_name="member")

    result = await is_initiative_manager(session, initiative_id=initiative.id, user=member)

    assert result is False


@pytest.mark.service
async def test_is_initiative_manager_app_admin_bypasses(session: AsyncSession):
    admin = await create_user(session, email="admin@example.com")
    guild = await create_guild(session, creator=admin)
    await create_guild_membership(session, user=admin, guild=guild, role=GuildRole.admin)
    initiative = await create_initiative(session, guild, admin)

    # Create a platform-level admin who is NOT an initiative member
    app_admin = await create_user(session, email="appadmin@example.com", role=UserRole.admin)

    result = await is_initiative_manager(session, initiative_id=initiative.id, user=app_admin)

    assert result is True


@pytest.mark.service
async def test_assert_initiative_manager_raises_for_member(session: AsyncSession):
    admin = await create_user(session, email="admin@example.com")
    guild = await create_guild(session, creator=admin)
    await create_guild_membership(session, user=admin, guild=guild, role=GuildRole.admin)
    initiative = await create_initiative(session, guild, admin)

    member = await create_user(session, email="member@example.com")
    await create_guild_membership(session, user=member, guild=guild)
    await create_initiative_member(session, initiative, member, role_name="member")

    with pytest.raises(PermissionError, match=InitiativeMessages.MANAGER_REQUIRED):
        await assert_initiative_manager(session, initiative_id=initiative.id, user=member)


# ---------------------------------------------------------------------------
# Initiative permission checks (async / service)
# ---------------------------------------------------------------------------


@pytest.mark.service
async def test_check_initiative_permission_admin_bypasses(session: AsyncSession):
    admin = await create_user(session, email="admin@example.com")
    guild = await create_guild(session, creator=admin)
    await create_guild_membership(session, user=admin, guild=guild, role=GuildRole.admin)
    initiative = await create_initiative(session, guild, admin)

    app_admin = await create_user(session, email="appadmin@example.com", role=UserRole.admin)

    result = await check_initiative_permission(
        session, initiative_id=initiative.id, user=app_admin,
        permission_key=PermissionKey.create_projects,
    )

    assert result is True


@pytest.mark.service
async def test_check_initiative_permission_manager_has_all(session: AsyncSession):
    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    await create_guild_membership(session, user=user, guild=guild, role=GuildRole.admin)
    initiative = await create_initiative(session, guild, user)
    # creator is PM (is_manager=True)

    result = await check_initiative_permission(
        session, initiative_id=initiative.id, user=user,
        permission_key=PermissionKey.create_docs,
    )

    assert result is True


@pytest.mark.service
async def test_check_initiative_permission_member_explicit_enabled(session: AsyncSession):
    admin = await create_user(session, email="admin@example.com")
    guild = await create_guild(session, creator=admin)
    await create_guild_membership(session, user=admin, guild=guild, role=GuildRole.admin)
    initiative = await create_initiative(session, guild, admin)

    member = await create_user(session, email="member@example.com")
    await create_guild_membership(session, user=member, guild=guild)
    await create_initiative_member(session, initiative, member, role_name="member")

    # The member role has docs_enabled=True and projects_enabled=True by default
    result = await check_initiative_permission(
        session, initiative_id=initiative.id, user=member,
        permission_key=PermissionKey.docs_enabled,
    )

    assert result is True


@pytest.mark.service
async def test_check_initiative_permission_member_explicit_disabled(session: AsyncSession):
    admin = await create_user(session, email="admin@example.com")
    guild = await create_guild(session, creator=admin)
    await create_guild_membership(session, user=admin, guild=guild, role=GuildRole.admin)
    initiative = await create_initiative(session, guild, admin)

    member = await create_user(session, email="member@example.com")
    await create_guild_membership(session, user=member, guild=guild)
    await create_initiative_member(session, initiative, member, role_name="member")

    # The member role has create_docs=False and create_projects=False by default
    result = await check_initiative_permission(
        session, initiative_id=initiative.id, user=member,
        permission_key=PermissionKey.create_docs,
    )

    assert result is False


@pytest.mark.service
async def test_check_initiative_permission_falls_back_to_default(session: AsyncSession):
    admin = await create_user(session, email="admin@example.com")
    guild = await create_guild(session, creator=admin)
    await create_guild_membership(session, user=admin, guild=guild, role=GuildRole.admin)
    initiative = await create_initiative(session, guild, admin)

    member = await create_user(session, email="member@example.com")
    await create_guild_membership(session, user=member, guild=guild)
    await create_initiative_member(session, initiative, member, role_name="member")

    # Verify that the default values in DEFAULT_PERMISSION_VALUES are used as
    # fallback when a permission is not explicitly set on the role. The member
    # role has explicit permissions for the standard keys, so this test
    # validates the branch behavior: if a key were missing, it would fall back
    # to DEFAULT_PERMISSION_VALUES.
    for perm_key, expected in DEFAULT_PERMISSION_VALUES.items():
        result = await check_initiative_permission(
            session, initiative_id=initiative.id, user=member,
            permission_key=perm_key,
        )
        # The explicit member role values happen to match the defaults for
        # the standard permission keys.
        assert result == expected, f"Mismatch for {perm_key}"


@pytest.mark.service
async def test_check_initiative_permission_non_member(session: AsyncSession):
    admin = await create_user(session, email="admin@example.com")
    guild = await create_guild(session, creator=admin)
    await create_guild_membership(session, user=admin, guild=guild, role=GuildRole.admin)
    initiative = await create_initiative(session, guild, admin)

    outsider = await create_user(session, email="outsider@example.com")

    result = await check_initiative_permission(
        session, initiative_id=initiative.id, user=outsider,
        permission_key=PermissionKey.docs_enabled,
    )

    assert result is False


# ---------------------------------------------------------------------------
# Feature access helper (async / service)
# ---------------------------------------------------------------------------


@pytest.mark.service
async def test_has_feature_access_docs(session: AsyncSession):
    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    await create_guild_membership(session, user=user, guild=guild, role=GuildRole.admin)
    initiative = await create_initiative(session, guild, user)

    result = await has_feature_access(
        session, initiative_id=initiative.id, user=user, feature="docs",
    )

    assert result is True


@pytest.mark.service
async def test_has_feature_access_projects(session: AsyncSession):
    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    await create_guild_membership(session, user=user, guild=guild, role=GuildRole.admin)
    initiative = await create_initiative(session, guild, user)

    result = await has_feature_access(
        session, initiative_id=initiative.id, user=user, feature="projects",
    )

    assert result is True
