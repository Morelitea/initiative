"""Per-member connections to an installed app's vendor, and how they end.

A member connects their own account, an admin governs who may, and every way
the relationship can end deletes the stored values and records a revocation.
That last part is the reason this module is one place rather than a helper
beside each caller: leaving a guild, being removed from it, being revoked or
blocked, deleting an account, uninstalling the app and deleting the guild are
six different stories with one requirement in common, and the way that
requirement gets missed is each story implementing it separately.

Every deletion path here goes through :func:`_delete_rows`, which is what makes
"the values are gone and the app has been told" a property of the module rather
than of each caller remembering.

The ``connection_ref`` an app addresses a credential by is minted once per
(install, connection, member) and reused across reconnects, so a member's
history stays one row. It is random rather than derived from anything about the
person, which is what keeps the same member uncorrelated across apps and guilds.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timezone
from typing import Any, Optional, Sequence

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.tenant.guild_app import GuildApp
from app.models.tenant.guild_app_user_connection import GuildAppUserConnection
from app.services.tenant.app_revocation import (
    RevocationIntent,
    queue_revocation,
    queue_revocations_for_rows,
)

__all__ = [
    "block_member_connection",
    "connect",
    "delete_app_connections",
    "delete_guild_connections",
    "delete_member_connections",
    "disconnect",
    "get_connection",
    "is_blocked",
    "list_app_connections",
    "list_member_connections",
    "mint_connection_ref",
    "revoke_all",
    "unblock_member_connection",
]

#: Long enough that a handle is never guessed, short enough to sit in a URL the
#: app builds. ``token_urlsafe(24)`` renders as 32 characters, which is the
#: column width.
_REF_ENTROPY_BYTES = 24


def mint_connection_ref() -> str:
    return secrets.token_urlsafe(_REF_ENTROPY_BYTES)


def _now() -> datetime:
    return datetime.now(timezone.utc)


# --- reading ----------------------------------------------------------------


async def get_connection(
    session: AsyncSession, *, app_id: int, connection_id: str, user_id: int
) -> Optional[GuildAppUserConnection]:
    """One member's row for one connection, if it exists.

    Under the table's own-row policies this returns the caller's row when the
    caller is the member, and any member's row when the session is routed as a
    guild admin — the same query either way, because the gate is in the
    database rather than in a branch here.
    """
    return (
        await session.exec(
            select(GuildAppUserConnection).where(
                GuildAppUserConnection.app_id == app_id,
                GuildAppUserConnection.connection_id == connection_id,
                GuildAppUserConnection.user_id == user_id,
            )
        )
    ).first()


async def list_member_connections(
    session: AsyncSession, *, app_id: int, user_id: int
) -> list[GuildAppUserConnection]:
    """Every connection this member holds for one install."""
    return list(
        (
            await session.exec(
                select(GuildAppUserConnection)
                .where(
                    GuildAppUserConnection.app_id == app_id,
                    GuildAppUserConnection.user_id == user_id,
                )
                .order_by(GuildAppUserConnection.connection_id)
            )
        ).all()
    )


async def list_app_connections(
    session: AsyncSession, *, app_id: int
) -> list[GuildAppUserConnection]:
    """Every member's connection for one install — the admin's Members view.

    Returns only the caller's own rows unless the session is routed as a guild
    admin; the endpoint that offers this requires one.
    """
    return list(
        (
            await session.exec(
                select(GuildAppUserConnection)
                .where(GuildAppUserConnection.app_id == app_id)
                .order_by(
                    GuildAppUserConnection.connection_id,
                    GuildAppUserConnection.user_id,
                )
            )
        ).all()
    )


# --- connecting -------------------------------------------------------------


async def connect(
    session: AsyncSession,
    *,
    app: GuildApp,
    connection_id: str,
    user_id: int,
) -> GuildAppUserConnection:
    """Start (or restart) this member's own connection, returning its row.

    The row and its ``connection_ref`` exist before the vendor flow does, so the
    app has something to write its result against. Reconnecting reuses the
    existing row and its ref: the app is already holding credentials under that
    handle, and handing it a new one would orphan them.

    A blocked member never reaches here — the endpoint refuses first — so this
    does not have to decide whether a tombstone may be revived.
    """
    existing = await get_connection(
        session, app_id=app.id, connection_id=connection_id, user_id=user_id
    )
    if existing is not None:
        existing.status = "pending"
        existing.updated_at = _now()
        session.add(existing)
        return existing

    row = GuildAppUserConnection(
        guild_id=app.guild_id,
        app_id=app.id,
        connection_id=connection_id,
        user_id=user_id,
        connection_ref=mint_connection_ref(),
        status="pending",
    )
    session.add(row)
    await session.flush()
    return row


# --- ending it --------------------------------------------------------------


async def _delete_rows(
    session: AsyncSession,
    rows: Sequence[GuildAppUserConnection],
    *,
    listing_uid: str,
    reason: str,
) -> int:
    """Delete stored credentials and record the matching revocations.

    The single choke point for ending per-member access: an intent is queued for
    every row before it goes, so no caller can delete values without the app
    being told which handle stopped being valid.
    """
    if not rows:
        return 0
    queue_revocations_for_rows(
        session, listing_uid=listing_uid, rows=rows, reason=reason
    )
    for row in rows:
        await session.delete(row)
    return len(rows)


async def disconnect(
    session: AsyncSession,
    *,
    app: GuildApp,
    connection_id: str,
    user_id: int,
    reason: str = "disconnected",
) -> int:
    """A member's own connection, or one an admin is ending for them."""
    row = await get_connection(
        session, app_id=app.id, connection_id=connection_id, user_id=user_id
    )
    if row is None:
        return 0
    return await _delete_rows(
        session, [row], listing_uid=app.listing_uid, reason=reason
    )


async def block_member_connection(
    session: AsyncSession,
    *,
    app: GuildApp,
    connection_id: str,
    user_id: int,
    blocked_by_id: int,
) -> GuildAppUserConnection:
    """Revoke a member's connection and stop them making another.

    The row survives as a tombstone holding ``blocked_at`` and who acted, which
    is what distinguishes "this person should no longer reach that system
    through us" from a revocation they could simply undo by clicking Connect
    again. The values go exactly as they do on any other revocation — a block
    that left the credential in place would be a worse outcome than a plain
    revoke, not a stronger one.
    """
    row = await get_connection(
        session, app_id=app.id, connection_id=connection_id, user_id=user_id
    )
    if row is None:
        row = GuildAppUserConnection(
            guild_id=app.guild_id,
            app_id=app.id,
            connection_id=connection_id,
            user_id=user_id,
            connection_ref=mint_connection_ref(),
            status="blocked",
        )
    else:
        queue_revocation(
            session,
            RevocationIntent(
                guild_id=row.guild_id,
                app_id=row.app_id,
                listing_uid=app.listing_uid,
                connection_id=row.connection_id,
                connection_ref=row.connection_ref,
                user_id=row.user_id,
                reason="blocked",
            ),
        )
        row.status = "blocked"

    row.config = {}
    row.config_secrets = {}
    row.account_label = None
    row.blocked_at = _now()
    row.blocked_by_id = blocked_by_id
    row.updated_at = _now()
    session.add(row)
    await session.flush()
    return row


async def unblock_member_connection(
    session: AsyncSession, *, app: GuildApp, connection_id: str, user_id: int
) -> bool:
    """Lift a block. The tombstone goes; the member may connect again."""
    row = await get_connection(
        session, app_id=app.id, connection_id=connection_id, user_id=user_id
    )
    if row is None or row.blocked_at is None:
        return False
    # Nothing to revoke — a blocked row holds no values — so the row is simply
    # removed and the member starts clean if they choose to reconnect.
    await session.delete(row)
    return True


async def revoke_all(
    session: AsyncSession, *, app: GuildApp, reason: str = "revoke_all"
) -> int:
    """Every member's connection for one install, at once.

    For a suspected app or vendor compromise: it ends access without tearing
    down the install, so an admin does not have to choose between reacting fast
    and keeping the app's configuration.
    """
    rows = [
        row
        for row in await list_app_connections(session, app_id=app.id)
        if row.blocked_at is None
    ]
    return await _delete_rows(session, rows, listing_uid=app.listing_uid, reason=reason)


async def delete_app_connections(
    session: AsyncSession, *, app: GuildApp, reason: str = "uninstalled"
) -> int:
    """Everything for one install, blocked tombstones included.

    Uninstalling ends the app's access completely, so a tombstone recording that
    somebody was blocked from an app that is no longer installed has nothing
    left to constrain.
    """
    rows = await list_app_connections(session, app_id=app.id)
    return await _delete_rows(session, rows, listing_uid=app.listing_uid, reason=reason)


async def delete_member_connections(
    session: AsyncSession, *, user_id: int, reason: str
) -> int:
    """Every connection one member holds in the routed guild.

    For the paths where the person's relationship with the guild ends — leaving,
    being removed, deactivating or deleting their account. Their connections in
    other guilds are untouched, because those relationships have not ended.

    The session must already be routed into the guild. Blocked tombstones are
    left alone: a block outlives a membership, so somebody removed and later
    re-invited does not come back with the block quietly lifted.
    """
    rows = list(
        (
            await session.exec(
                select(GuildAppUserConnection).where(
                    GuildAppUserConnection.user_id == user_id,
                    GuildAppUserConnection.blocked_at.is_(None),
                )
            )
        ).all()
    )
    if not rows:
        return 0

    listing_uids = await _listing_uids_by_app_id(
        session, app_ids={row.app_id for row in rows}
    )
    for row in rows:
        queue_revocation(
            session,
            RevocationIntent(
                guild_id=row.guild_id,
                app_id=row.app_id,
                listing_uid=listing_uids.get(row.app_id, ""),
                connection_id=row.connection_id,
                connection_ref=row.connection_ref,
                user_id=row.user_id,
                reason=reason,
            ),
        )
        await session.delete(row)
    return len(rows)


async def delete_guild_connections(
    session: AsyncSession, *, reason: str = "guild_deleted"
) -> int:
    """Every connection in the routed guild, before the guild goes.

    Dropping the schema would remove the rows without anyone being told, which
    would leave vendor grants outliving the guild that authorized them. This
    runs first so each app is asked to let go.
    """
    rows = list((await session.exec(select(GuildAppUserConnection))).all())
    if not rows:
        return 0
    listing_uids = await _listing_uids_by_app_id(
        session, app_ids={row.app_id for row in rows}
    )
    for row in rows:
        queue_revocation(
            session,
            RevocationIntent(
                guild_id=row.guild_id,
                app_id=row.app_id,
                listing_uid=listing_uids.get(row.app_id, ""),
                connection_id=row.connection_id,
                connection_ref=row.connection_ref,
                user_id=row.user_id,
                reason=reason,
            ),
        )
        await session.delete(row)
    return len(rows)


async def _listing_uids_by_app_id(
    session: AsyncSession, *, app_ids: set[int]
) -> dict[int, str]:
    """Which listing each install came from, for the revocation address."""
    if not app_ids:
        return {}
    rows = (
        await session.exec(
            select(GuildApp.id, GuildApp.listing_uid).where(GuildApp.id.in_(app_ids))
        )
    ).all()
    return {row[0]: row[1] for row in rows}


def is_blocked(row: Optional[Any]) -> bool:
    """Whether a member has been stopped from connecting this one."""
    return row is not None and row.blocked_at is not None
