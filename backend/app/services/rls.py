"""Mandatory Access Control — RLS and guild/initiative-level security.

This module centralizes all Row-Level Security (RLS) related application
logic, guild-level access checks, and initiative-level access checks.
It is the single source of truth for understanding what the database
enforces and for performing access checks in the application layer.

Security layers managed here:
  1. Guild isolation  — PERMISSIVE RLS: guild_id = current_guild_id
     All guild members can *read* data within their guild.
  2. Guild RBAC       — Only guild admins may write/update/delete
     guild-scoped configuration (guild settings, invites, initiatives).
     Members can only read and participate via subsequent layers.
     Enforced in application code: ``require_guild_admin()``,
     ``is_guild_admin()``, ``require_guild_membership()``.
  3. Initiative membership — RESTRICTIVE RLS: is_initiative_member()
  4. Initiative RBAC — Application-level feature access via PermissionKey

The complementary DAC (Discretionary Access Control) layer for
project/document-level permissions lives in ``permissions.py``.
"""

from __future__ import annotations

from fastapi import HTTPException, status
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.messages import GuildMessages, InitiativeMessages
from app.models.guild import GuildMembership, GuildRole
from app.models.initiative import (
    InitiativeMember,
    InitiativeRoleModel,
    PermissionKey,
    DEFAULT_PERMISSION_VALUES,
)
from app.models.user import User, UserRole

# Re-export RLS context helpers so callers can import from a single place.
from app.db.session import set_rls_context, reapply_rls_context  # noqa: F401


# ---------------------------------------------------------------------------
# Guild-level access checks
# ---------------------------------------------------------------------------

def is_guild_admin(guild_role: GuildRole) -> bool:
    """Check if the given guild role is admin."""
    return guild_role == GuildRole.admin


def require_guild_admin(guild_role: GuildRole) -> None:
    """Raise HTTPException(403) unless the guild role is admin.

    Use this for operations that only guild admins may perform:
    creating initiatives, managing guild settings, managing invites, etc.
    """
    if guild_role != GuildRole.admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=GuildMessages.GUILD_ADMIN_REQUIRED,
        )


async def get_guild_membership(
    session: AsyncSession,
    *,
    guild_id: int,
    user_id: int,
) -> GuildMembership | None:
    """Look up a user's guild membership."""
    from sqlmodel import select

    stmt = select(GuildMembership).where(
        GuildMembership.guild_id == guild_id,
        GuildMembership.user_id == user_id,
    )
    result = await session.exec(stmt)
    return result.one_or_none()


async def require_guild_membership(
    session: AsyncSession,
    *,
    guild_id: int,
    user_id: int,
) -> GuildMembership:
    """Return the membership or raise 403."""
    membership = await get_guild_membership(
        session, guild_id=guild_id, user_id=user_id,
    )
    if not membership:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=GuildMessages.NOT_GUILD_MEMBER,
        )
    return membership


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

async def _get_membership_with_role(
    session: AsyncSession,
    *,
    initiative_id: int,
    user_id: int,
) -> InitiativeMember | None:
    """Get initiative membership with role eagerly loaded."""
    from sqlalchemy.orm import selectinload
    from sqlmodel import select

    stmt = (
        select(InitiativeMember)
        .options(selectinload(InitiativeMember.role_ref).selectinload(InitiativeRoleModel.permissions))
        .where(
            InitiativeMember.initiative_id == initiative_id,
            InitiativeMember.user_id == user_id,
        )
    )
    result = await session.exec(stmt)
    return result.one_or_none()


# ---------------------------------------------------------------------------
# Initiative manager checks
# ---------------------------------------------------------------------------

async def is_initiative_manager(
    session: AsyncSession,
    *,
    initiative_id: int,
    user: User,
) -> bool:
    """Check if user has manager-level role in the initiative."""
    if user.role == UserRole.admin:
        return True
    membership = await _get_membership_with_role(
        session, initiative_id=initiative_id, user_id=user.id
    )
    if not membership or not membership.role_ref:
        return False
    return membership.role_ref.is_manager


async def assert_initiative_manager(
    session: AsyncSession,
    *,
    initiative_id: int,
    user: User,
) -> None:
    """Raise ``PermissionError`` unless user is an initiative manager."""
    if await is_initiative_manager(session, initiative_id=initiative_id, user=user):
        return
    raise PermissionError(InitiativeMessages.MANAGER_REQUIRED)


# ---------------------------------------------------------------------------
# Initiative permission checks (RBAC via PermissionKey)
# ---------------------------------------------------------------------------

async def check_initiative_permission(
    session: AsyncSession,
    *,
    initiative_id: int,
    user: User,
    permission_key: PermissionKey | str,
) -> bool:
    """Check if user has a specific permission in the initiative.

    Args:
        session: Database session
        initiative_id: ID of the initiative
        user: User to check permissions for
        permission_key: Permission to check (e.g., PermissionKey.create_docs)

    Returns:
        True if user has the permission, False otherwise
    """
    # App admins bypass permission checks
    if user.role == UserRole.admin:
        return True

    membership = await _get_membership_with_role(
        session, initiative_id=initiative_id, user_id=user.id
    )
    if not membership or not membership.role_ref:
        return False

    # Managers with is_manager=True have all permissions
    if membership.role_ref.is_manager:
        return True

    # Check specific permission
    perm_key_enum = permission_key if isinstance(permission_key, PermissionKey) else PermissionKey(permission_key)
    perm_key_str = perm_key_enum.value
    for perm in membership.role_ref.permissions:
        if perm.permission_key == perm_key_str:
            return perm.enabled

    # Permission not explicitly set - use documented default
    return DEFAULT_PERMISSION_VALUES.get(perm_key_enum, False)


async def has_feature_access(
    session: AsyncSession,
    *,
    initiative_id: int,
    user: User,
    feature: str,
) -> bool:
    """Check if user can see a feature (docs or projects).

    Args:
        feature: Either "docs" or "projects"
    """
    perm_key = PermissionKey.docs_enabled if feature == "docs" else PermissionKey.projects_enabled
    return await check_initiative_permission(
        session,
        initiative_id=initiative_id,
        user=user,
        permission_key=perm_key,
    )
