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
  3. Initiative membership — PERMISSIVE RLS on every guild-schema content
     table, all deferring to ``public.initiative_access()`` (the single
     source of truth: initiative member OR guild admin OR PAM grant).
  4. Initiative RBAC — Application-level feature access via PermissionKey

The complementary DAC (Discretionary Access Control) layer for
project/document-level permissions lives in ``permissions.py``.
"""

from __future__ import annotations

from fastapi import HTTPException, status
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.messages import GuildMessages, InitiativeMessages
from app.models.platform.guild import GuildMembership, GuildRole
from app.models.tenant.initiative import (
    InitiativeMember,
    InitiativeRoleModel,
    PermissionKey,
    DEFAULT_PERMISSION_VALUES,
)
from app.models.platform.user import User

# Re-export the RLS context helper so callers can import from a single place.
from app.db.session import set_rls_context  # noqa: F401


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
        session,
        guild_id=guild_id,
        user_id=user_id,
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
        .options(
            selectinload(InitiativeMember.role_ref).selectinload(
                InitiativeRoleModel.permissions
            )
        )
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
    # No standing platform bypass: ``data.bypass`` no longer confers manager
    # authority. An admin/owner reaches a guild only via an explicit break-glass
    # grant, and a grant — like the existing PAM model — confers scoped content
    # read/write (enforced by RLS + the resource-access helpers), never initiative
    # management. So manager status is membership-derived only.
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
    permission_key: PermissionKey,
) -> bool:
    """Check if user has a specific permission in the initiative.

    Args:
        session: Database session
        initiative_id: ID of the initiative
        user: User to check permissions for
        permission_key: Permission to check (e.g., PermissionKey.create_documents)

    Returns:
        True if user has the permission, False otherwise
    """
    # No standing platform bypass: ``data.bypass`` no longer grants every
    # permission. A break-glass / PAM grantee's content visibility and read/write
    # are handled by the dedicated PAM path (list filters' ``has_active_grant``,
    # the ``require_*_access`` helpers, and RLS at the assumed guild role) — a
    # grant never confers initiative-level permission keys here, so permission is
    # membership-derived only.
    membership = await _get_membership_with_role(
        session, initiative_id=initiative_id, user_id=user.id
    )
    return _role_grants(membership.role_ref if membership else None, permission_key)


def _role_grants(
    role_ref: InitiativeRoleModel | None, permission_key: PermissionKey
) -> bool:
    """Resolve a single role's grant for ``permission_key`` — the same rule as
    :func:`check_initiative_permission` (manager ⇒ all; explicit row; else the
    documented default), factored out so the bulk resolver can't drift from it."""
    if role_ref is None:
        return False
    if role_ref.is_manager:
        return True
    for perm in role_ref.permissions:
        if perm.permission_key == permission_key:
            return perm.enabled
    return DEFAULT_PERMISSION_VALUES.get(permission_key, False)


async def accessible_initiative_ids(
    session: AsyncSession,
    *,
    user: User,
    permission_key: PermissionKey,
) -> set[int]:
    """Initiative ids (in the routed guild schema) where the user's initiative
    role grants ``permission_key`` — the bulk form of
    :func:`check_initiative_permission`, for scoping tool *lists* to the SAME
    role-permission the frontend reflects.

    One query over the user's memberships (bounded by how many initiatives they're
    in), so it stays cheap at scale; the per-row decision reuses ``_role_grants``.
    Guild-admin / PAM are handled separately by the caller (they see everything);
    this is purely the membership-role tier.
    """
    from sqlalchemy.orm import selectinload
    from sqlmodel import select

    stmt = (
        select(InitiativeMember)
        .options(
            selectinload(InitiativeMember.role_ref).selectinload(
                InitiativeRoleModel.permissions
            )
        )
        .where(InitiativeMember.user_id == user.id)
    )
    rows = (await session.exec(stmt)).all()
    return {m.initiative_id for m in rows if _role_grants(m.role_ref, permission_key)}


async def override_sharing_initiative_ids(
    session: AsyncSession,
    *,
    user_id: int,
) -> set[int]:
    """Initiative ids (in the routed guild schema) where the user holds a role
    with ``override_share_restrictions`` ("Full access") — the set the request's
    DAC override consults (``role_context.request_overrides_sharing``).

    One indexed query over the user's memberships, joined to their role. Called
    once per guild request at session establishment; usually returns the empty
    set (most users are full-access PMs nowhere).
    """
    from sqlmodel import select

    stmt = (
        select(InitiativeMember.initiative_id)
        .join(
            InitiativeRoleModel,
            InitiativeRoleModel.id == InitiativeMember.role_id,
        )
        .where(
            InitiativeMember.user_id == user_id,
            InitiativeRoleModel.override_share_restrictions.is_(True),
        )
    )
    return set((await session.exec(stmt)).all())
