"""Whether an installed app may act as a particular member, and how.

The guild's admins decide an app is here; each member decides, for themselves,
whether it may make requests carrying their own name. This module owns the
second half — the record, the levers that end it, and the read the auth path
makes on every delegated call.

Three shapes of ending, and they mean different things:

* **Withdrawn** (:func:`revoke`) — the grant stops, the row stays holding
  ``revoked_at``. The member may authorize again; what a delete would lose is
  that they once did and then stopped.
* **Everyone at once** (:func:`revoke_all`) — the same, for every member of one
  install, without tearing the install down.
* **Gone with the relationship** (:func:`delete_member_delegations`,
  :func:`delete_app_delegations`) — the person left the guild, or the app was
  removed. Nothing survives an ended relationship, tombstones included: there
  is no longer a party for the record to constrain.

:func:`authorized` is the one the request path calls. It reads the row per
call rather than caching, because withdrawing authorization is expected to bite
on the very next request.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import delete as sa_delete
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.tenant.guild_app import GuildApp
from app.models.tenant.guild_app_user_delegation import GuildAppUserDelegation

__all__ = [
    "authorized",
    "delete_app_delegations",
    "delete_member_delegations",
    "get_delegation",
    "grant",
    "is_active",
    "list_app_delegations",
    "revoke",
    "revoke_all",
]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def is_active(row: Optional[GuildAppUserDelegation]) -> bool:
    """Whether a row is a grant in force rather than a record of a past one."""
    return row is not None and row.revoked_at is None and row.can_read


# --- reading ----------------------------------------------------------------


async def get_delegation(
    session: AsyncSession, *, app_id: int, user_id: int
) -> Optional[GuildAppUserDelegation]:
    """One member's row for one install, in force or withdrawn.

    Under the table's own-row policies this returns the caller's row when the
    caller is the member, and any member's row when the session is routed as a
    guild admin — the same query either way, because the gate is in the
    database rather than in a branch here.
    """
    return (
        await session.exec(
            select(GuildAppUserDelegation).where(
                GuildAppUserDelegation.app_id == app_id,
                GuildAppUserDelegation.user_id == user_id,
            )
        )
    ).first()


async def list_app_delegations(
    session: AsyncSession, *, app_id: int
) -> list[GuildAppUserDelegation]:
    """Every member's row for one install — the admin's Members view.

    Returns only the caller's own row unless the session is routed as a guild
    admin; the endpoint that offers this requires one.
    """
    return list(
        (
            await session.exec(
                select(GuildAppUserDelegation)
                .where(GuildAppUserDelegation.app_id == app_id)
                .order_by(GuildAppUserDelegation.user_id)
            )
        ).all()
    )


# --- granting ---------------------------------------------------------------


async def grant(
    session: AsyncSession,
    *,
    app: GuildApp,
    user_id: int,
    can_write: bool,
    confirmed_factor: Optional[str] = None,
) -> GuildAppUserDelegation:
    """Authorize the app to act as this member, at the depth given.

    ``can_read`` is not a parameter: a grant that did not let the app act would
    be the same as no grant, so authorizing at all is authorizing reads, and
    ``can_write`` is the one question left to answer. Withdrawing is how a
    member says no.

    Re-authorizing after a withdrawal reuses the row and restarts
    ``granted_at``, which keeps a member's history with one app to one row while
    still reporting the age of what is actually in force.
    """
    row = await get_delegation(session, app_id=app.id, user_id=user_id)
    if row is None:
        row = GuildAppUserDelegation(
            guild_id=app.guild_id,
            app_id=app.id,
            user_id=user_id,
        )
    row.can_read = True
    row.can_write = can_write
    row.granted_at = _now()
    row.revoked_at = None
    row.revoked_by_id = None
    row.confirmed_factor = confirmed_factor
    row.updated_at = _now()
    session.add(row)
    await session.flush()
    return row


# --- ending it --------------------------------------------------------------


def _mark_revoked(row: GuildAppUserDelegation, *, revoked_by_id: int) -> None:
    row.can_read = False
    row.can_write = False
    row.revoked_at = _now()
    row.revoked_by_id = revoked_by_id
    row.updated_at = _now()


async def revoke(
    session: AsyncSession,
    *,
    app_id: int,
    user_id: int,
    revoked_by_id: int,
) -> bool:
    """Withdraw one member's grant, leaving the record of it.

    Returns whether anything was in force to withdraw, so a caller can tell a
    real withdrawal from a repeat of one.
    """
    row = await get_delegation(session, app_id=app_id, user_id=user_id)
    if row is None or row.revoked_at is not None:
        return False
    _mark_revoked(row, revoked_by_id=revoked_by_id)
    session.add(row)
    return True


async def revoke_all(session: AsyncSession, *, app_id: int, revoked_by_id: int) -> int:
    """Withdraw every member's grant for one install, at once.

    The lever for a suspected app compromise: it stops the app acting as anyone
    without uninstalling it, so reacting fast does not cost the guild its
    configuration. Members may authorize again once the guild is satisfied.
    """
    rows = [
        row
        for row in await list_app_delegations(session, app_id=app_id)
        if row.revoked_at is None
    ]
    for row in rows:
        _mark_revoked(row, revoked_by_id=revoked_by_id)
        session.add(row)
    return len(rows)


async def delete_app_delegations(session: AsyncSession, *, app_id: int) -> int:
    """Everything for one install, withdrawn rows included.

    For uninstall. A record that somebody once authorized an app the guild no
    longer has constrains nothing, so it goes with the app.

    Issued as one statement rather than row-by-row: the caller deletes the
    install in the same transaction, and the ORM is free to order that first —
    at which point the FK cascade has already taken these and the per-row
    deletes match nothing.
    """
    result = await session.exec(
        sa_delete(GuildAppUserDelegation).where(GuildAppUserDelegation.app_id == app_id)
    )
    return result.rowcount or 0


async def delete_member_delegations(session: AsyncSession, *, user_id: int) -> int:
    """Every grant one member holds in the routed guild.

    For the paths where the person's relationship with the guild ends — leaving,
    being removed, deactivating or deleting their account. Their grants in other
    guilds are untouched, because those relationships have not ended.

    The session must already be routed into the guild.
    """
    result = await session.exec(
        sa_delete(GuildAppUserDelegation).where(
            GuildAppUserDelegation.user_id == user_id
        )
    )
    return result.rowcount or 0


# --- the read the auth path makes -------------------------------------------


async def authorized(
    session: AsyncSession, *, app_id: int, user_id: int, need_write: bool
) -> bool:
    """Whether this member's grant covers what the call is about to do.

    The session must already be routed into the guild. Deliberately a fresh
    read on every delegated call: an install and a registration can each afford
    to be cached, but withdrawing authorization is a member's own decision about
    their own name, and it is expected to take effect at once.
    """
    row = await get_delegation(session, app_id=app_id, user_id=user_id)
    if not is_active(row):
        return False
    return row.can_write if need_write else True
