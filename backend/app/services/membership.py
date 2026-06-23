"""Shared guild- and initiative-membership checks.

Initiative scoping has **one** definition: the ``public.initiative_access`` SQL
function (initiative member OR guild admin OR PAM grant, read from the request
GUCs). The guild-schema RLS policies call it as the fail-closed DB backstop, and
``initiative_scope_clause`` here calls the *same* function so app-built queries
use the identical rule — no parallel re-implementation. This module also provides
the guild/initiative-membership batch lookups (resolve membership for many users
or initiatives in one round trip instead of a per-user loop).

Routing contract:
  - ``guild_memberships`` is a shared/public table — the guild helpers work on
    any session, routed or not.
  - ``initiative_members`` lives in each guild's schema — callers must already
    be routed into the right guild (``RLSSessionDep`` or ``set_rls_context``)
    before using the initiative helpers, exactly like any other guild-scoped
    query.
"""

from typing import Collection, Iterable, Optional

from sqlalchemy import ColumnElement, exists, func, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.guild import GuildMembership, GuildRole
from app.models.tenant.initiative import InitiativeMember


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


def initiative_scope_clause(
    user_id: int,
    initiative_id_col: ColumnElement[int] | int,
    guild_id_col: ColumnElement[int] | int | None = None,
    *,
    need_write: bool = False,
) -> ColumnElement[bool]:
    """Initiative-scope predicate for embedding in any SELECT — the **single
    source of truth**: it defers to the ``public.initiative_access`` SQL function
    (initiative member OR guild admin OR PAM grant, read from the request GUCs),
    the exact same predicate the guild-schema RLS policies use. There is one rule,
    in one place, called by both the database and the app.

    Because the function reads ``app.current_guild_role`` / ``app.pam_*`` from the
    session GUCs, the guild-admin and PAM legs come "for free" on any routed
    session (``RLSSessionDep`` or a per-guild ``set_rls_context``); ``guild_id_col``
    is accepted for call-site compatibility but no longer needed. ``need_write``
    selects the read vs. write PAM leg.
    """
    return func.initiative_access(initiative_id_col, user_id, need_write)


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
    return set((await session.exec(stmt)).all())


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
    return set((await session.exec(stmt)).all())


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
    return set((await session.exec(stmt)).all())


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
    rows = await session.exec(
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
