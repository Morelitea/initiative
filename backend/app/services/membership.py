"""Shared guild- and initiative-membership checks.

The schema-per-guild cutover removed the DB-level initiative-membership
RESTRICTIVE policy layer (``is_initiative_member()``), so initiative scoping
is now enforced entirely in application code. This module is the single
source of truth for those checks: clause builders for embedding membership
predicates in any SELECT, and batch lookups that resolve membership for many
users (or many initiatives) in one round trip instead of a per-user loop.

Routing contract:
  - ``guild_memberships`` is a shared/public table — the guild helpers work on
    any session, routed or not.
  - ``initiative_members`` lives in each guild's schema — callers must already
    be routed into the right guild (``RLSSessionDep`` or ``set_rls_context``)
    before using the initiative helpers, exactly like any other guild-scoped
    query.
"""

from typing import Collection, Iterable, Optional

from sqlalchemy import ColumnElement, exists, or_, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.capabilities import Capability, roles_with_capability
from app.core.pam_context import active_grant_guild
from app.models.guild import GuildMembership, GuildRole
from app.models.initiative import InitiativeMember
from app.models.user import User


# ---------------------------------------------------------------------------
# Clause builders — compose into WHERE conditions of any statement
# ---------------------------------------------------------------------------


def initiative_member_clause(
    user_id: int, initiative_id_col: ColumnElement[int] | int
) -> ColumnElement[bool]:
    """EXISTS predicate: ``user_id`` is a member of the referenced initiative.

    ``initiative_id_col`` is typically a column on the outer statement
    (e.g. ``Document.initiative_id``) but a literal id also works.
    """
    return exists(
        select(1).where(
            InitiativeMember.initiative_id == initiative_id_col,
            InitiativeMember.user_id == user_id,
        )
    )


def guild_member_clause(
    user_id: int,
    guild_id_col: ColumnElement[int] | int,
    *,
    role: Optional[GuildRole] = None,
) -> ColumnElement[bool]:
    """EXISTS predicate: ``user_id`` belongs to the referenced guild.

    Pass ``role=GuildRole.admin`` to require a specific guild role.
    """
    conditions = [
        GuildMembership.guild_id == guild_id_col,
        GuildMembership.user_id == user_id,
    ]
    if role is not None:
        conditions.append(GuildMembership.role == role)
    return exists(select(1).where(*conditions))


def initiative_access_clause(
    user_id: int,
    initiative_id_col: ColumnElement[int] | int,
    guild_id_col: ColumnElement[int] | int,
) -> ColumnElement[bool]:
    """The app-level replacement for the old RESTRICTIVE RLS expression
    ``is_initiative_member(...) OR guild-admin OR superadmin``: member of the
    initiative, or admin of the guild that owns it.

    The superadmin leg is intentionally not encoded in SQL — callers that
    serve ``data.bypass`` holders skip the gate instead (they can see the
    user object; the query cannot).
    """
    return or_(
        initiative_member_clause(user_id, initiative_id_col),
        guild_member_clause(user_id, guild_id_col, role=GuildRole.admin),
    )


def initiative_scope_clause(
    user_id: int,
    initiative_id_col: ColumnElement[int] | int,
    guild_id_col: ColumnElement[int] | int,
) -> ColumnElement[bool]:
    """Full app-level replacement for the old RESTRICTIVE RLS expression
    ``is_initiative_member(...) OR IS_ADMIN OR IS_SUPER``, evaluated per row in
    SQL so it stays correct inside cross-guild gathers and arbitrary batch
    sizes: initiative member, OR admin of the row's guild, OR a platform role
    holding ``data.bypass``, OR a live PAM grant covering the row's guild.

    The PAM leg mirrors the old ``is_initiative_member()`` SQL function (which
    honored the ``app.pam_*`` GUCs): the request's active grant — if any — is
    embedded as a literal guild predicate at build time, keeping this clause
    consistent with the loaded-data gate (``initiative_scope_ok``). Build the
    clause per request, inside the request's context.
    """
    bypass_roles = tuple(roles_with_capability(Capability.DATA_BYPASS))
    legs = [
        initiative_access_clause(user_id, initiative_id_col, guild_id_col),
        exists(select(1).where(User.id == user_id, User.role.in_(bypass_roles))),
    ]
    granted_guild = active_grant_guild()
    if granted_guild is not None:
        legs.append(guild_id_col == granted_guild)
    return or_(*legs)


def member_initiative_ids_select(user_id: int):
    """SELECT of initiative ids the user belongs to, for use as a subquery
    (``Entity.initiative_id.in_(member_initiative_ids_select(uid))``)."""
    return select(InitiativeMember.initiative_id).where(
        InitiativeMember.user_id == user_id
    )


# ---------------------------------------------------------------------------
# Batch lookups — one query regardless of how many users/initiatives
# ---------------------------------------------------------------------------


async def initiative_member_user_ids(
    session: AsyncSession,
    initiative_id: int,
    user_ids: Optional[Collection[int]] = None,
) -> set[int]:
    """The subset of ``user_ids`` that are members of the initiative
    (every member when ``user_ids`` is None). One query for any batch size."""
    stmt = select(InitiativeMember.user_id).where(
        InitiativeMember.initiative_id == initiative_id
    )
    if user_ids is not None:
        if not user_ids:
            return set()
        stmt = stmt.where(InitiativeMember.user_id.in_(tuple(set(user_ids))))
    return set((await session.execute(stmt)).scalars().all())


async def user_member_initiative_ids(
    session: AsyncSession,
    user_id: int,
    initiative_ids: Optional[Collection[int]] = None,
) -> set[int]:
    """The subset of ``initiative_ids`` the user is a member of (all of the
    user's initiatives in the routed guild when ``initiative_ids`` is None)."""
    stmt = select(InitiativeMember.initiative_id).where(
        InitiativeMember.user_id == user_id
    )
    if initiative_ids is not None:
        if not initiative_ids:
            return set()
        stmt = stmt.where(
            InitiativeMember.initiative_id.in_(tuple(set(initiative_ids)))
        )
    return set((await session.execute(stmt)).scalars().all())


async def is_initiative_member(
    session: AsyncSession, initiative_id: int, user_id: int
) -> bool:
    """Single-user convenience over :func:`initiative_member_user_ids`."""
    return bool(await initiative_member_user_ids(session, initiative_id, (user_id,)))


async def guild_member_user_ids(
    session: AsyncSession,
    guild_id: int,
    user_ids: Optional[Collection[int]] = None,
) -> set[int]:
    """The subset of ``user_ids`` that belong to the guild (every member when
    ``user_ids`` is None). Shared table — no guild routing required."""
    stmt = select(GuildMembership.user_id).where(GuildMembership.guild_id == guild_id)
    if user_ids is not None:
        if not user_ids:
            return set()
        stmt = stmt.where(GuildMembership.user_id.in_(tuple(set(user_ids))))
    return set((await session.execute(stmt)).scalars().all())


async def guild_role_map(
    session: AsyncSession,
    guild_id: int,
    user_ids: Iterable[int],
) -> dict[int, GuildRole]:
    """Guild role per user for a batch of users in one query. Users without a
    membership are absent from the result."""
    ids = tuple(set(user_ids))
    if not ids:
        return {}
    rows = await session.execute(
        select(GuildMembership.user_id, GuildMembership.role).where(
            GuildMembership.guild_id == guild_id,
            GuildMembership.user_id.in_(ids),
        )
    )
    return {user_id: role for user_id, role in rows.all()}


async def is_guild_admin(session: AsyncSession, guild_id: int, user_id: int) -> bool:
    """Whether the user is an admin of the guild. Shared table — works on any
    session."""
    role = (await guild_role_map(session, guild_id, (user_id,))).get(user_id)
    return role == GuildRole.admin
