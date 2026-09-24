"""Destroy guilds whose retention window has run out.

Deleting a guild no longer destroys it: it moves to ``GuildStatus.deleted``
and keeps everything — the shared rows, the ``guild_<id>`` schema, the stored
blobs — so a platform operator can put the community back. This worker is what
eventually does the destroying, and it does exactly what the delete used to do
inline: remove the shared guild row (whose ``ON DELETE CASCADE`` clears the
roster), forget the identities its apps knew its members by, then drop the
schema and purge the blobs. Each pass then reclaims any ``guild_<id>`` schema
whose row is already gone — a teardown that deleted the row but did not finish
dropping the schema, here or where a guild's creation was rolled back.

Before any of that, each pass deletes the communities whose hold has run out:
one left ``on_hold`` for longer than the deployment's hold window moves to
``deleted`` exactly as a deletion from its danger zone would, and the
retention window then starts like any other.

Polled by ``background_tasks._loop_worker`` once an hour on ``SystemSessionLocal``
(the ``app_admin`` login). It works on ``public.guilds`` alone and never routes
into a guild schema — the schema is dropped wholesale on the provisioning
engine, so there is nothing here to read inside it.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging

from sqlalchemy import text
from sqlmodel import delete, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.audit_events import AuditEventType
from app.db.schema_provisioning import deprovision_guild
from app.db.session import SystemSessionLocal, set_rls_context
from app.models.platform.guild import Guild, GuildStatus
from app.services import audit as audit_service
from app.services.marketplace import app_refs


logger = logging.getLogger(__name__)


GUILD_PURGE_POLL_SECONDS = 3600


def purge_at(deleted_at: datetime, retention_days: int) -> datetime:
    """When a guild deleted at ``deleted_at`` is destroyed."""
    return deleted_at + timedelta(days=retention_days)


async def retention_days(session: AsyncSession) -> int | None:
    """This deployment's window, or None where it keeps deleted communities.

    Read per sweep rather than cached: an operator who has just turned the
    window off is asking for the next sweep to destroy nothing, and a figure
    read at import would destroy something first.
    """
    from app.services.platform import app_settings as app_settings_service

    row = await app_settings_service.get_app_settings(session)
    return row.deleted_community_retention_days


async def hold_deletion_days(session: AsyncSession) -> int | None:
    """This deployment's hold window, or None where a hold never runs out.

    Read per sweep, like the retention window, so a change applies to the next
    pass rather than after a restart.
    """
    from app.services.platform import app_settings as app_settings_service

    row = await app_settings_service.get_app_settings(session)
    return row.on_hold_community_deletion_days


def hold_deletes_at(held_at: datetime, days: int) -> datetime:
    """When a community put on hold at ``held_at`` is deleted."""
    return held_at + timedelta(days=days)


async def _lock_expired_hold(
    session: AsyncSession, guild_id: int, *, cutoff: datetime
) -> Guild | None:
    """The guild, locked, if it is still on hold and was put there by
    ``cutoff``; None if the hold was lifted since the pass began."""
    return (
        await session.exec(
            select(Guild)
            .where(
                Guild.id == guild_id,
                Guild.status == GuildStatus.on_hold.value,
                Guild.status_changed_at.is_not(None),
                Guild.status_changed_at <= cutoff,
            )
            .with_for_update()
        )
    ).one_or_none()


async def _delete_expired_hold(
    session: AsyncSession, guild_id: int, *, cutoff: datetime
) -> bool:
    """Delete one community whose hold has run out. Mirrors the danger-zone
    delete: its apps let go, the status moves to ``deleted``, the seat is
    written to, and billing is told to read what happened.

    One transaction from the lock to the status write, so a hold lifted while
    the pass runs leaves the community exactly as it was. Nobody asked for
    this deletion, so the roster stays whatever its size.
    """
    from app.services import email as email_service
    from app.services.platform import billing_ping
    from app.services.platform import guilds as guilds_service
    from app.services.tenant import app_connections as app_connections_service
    from app.services.tenant import app_revocation as app_revocation_service

    await set_rls_context(session)
    guild = await _lock_expired_hold(session, guild_id, cutoff=cutoff)
    if guild is None:
        await session.commit()
        return False

    # Its connections live in its own schema. Flushed before routing back out,
    # because the deletes have to run where the rows are.
    await set_rls_context(session, guild_id=guild_id)
    await app_connections_service.delete_guild_connections(session)
    await session.flush()
    await set_rls_context(session)

    notice = await guilds_service.soft_delete_guild(
        session, guild, via="hold_expired", keep_roster=True
    )
    await session.commit()

    await email_service.announce_community_deleted(session, notice)
    # These live on other connections, so they go after the commit that made
    # the deletion real.
    await app_refs.forget_guild(guild_id=guild_id, keep_billing=True)
    billing_ping.notify_lifecycle_changed(guild_id)
    await app_revocation_service.dispatch_revocations(
        app_revocation_service.drain_revocations(session)
    )
    return True


async def delete_expired_holds(session: AsyncSession, *, now: datetime) -> int:
    """One pass over held communities. Returns how many were deleted.

    Counted from ``status_changed_at``, which is stamped when a community is
    put on hold and not again while it stays there, so a hold written twice
    does not restart the clock.
    """
    from app.services.tenant import app_revocation as app_revocation_service

    await set_rls_context(session)
    days = await hold_deletion_days(session)
    if days is None:
        return 0
    cutoff = now - timedelta(days=days)
    guild_ids = list(
        await session.exec(
            select(Guild.id)
            .where(
                Guild.status == GuildStatus.on_hold.value,
                Guild.status_changed_at.is_not(None),
                Guild.status_changed_at <= cutoff,
            )
            .order_by(Guild.status_changed_at.asc())
        )
    )
    await session.commit()
    deleted = 0
    for guild_id in guild_ids:
        # ids collide across schemas, so clear the identity map between guilds.
        session.expunge_all()
        try:
            if await _delete_expired_hold(session, guild_id, cutoff=cutoff):
                deleted += 1
        except Exception:
            # One community that fails must not hold up the rest; it is due
            # again on the next pass.
            logger.exception("guild purge: deleting held guild %s failed", guild_id)
            await session.rollback()
            # Nothing was taken away, so there is nothing to tell an app.
            app_revocation_service.drain_revocations(session)
    if deleted:
        logger.info("guild purge: deleted %d guild(s) whose hold ran out", deleted)
    return deleted


async def _due_guild_ids(
    session: AsyncSession, *, now: datetime, retention: int
) -> list[int]:
    """Guilds whose retention has run out, oldest deletion first.

    A ``deleted`` row with no ``status_changed_at`` cannot happen — the delete
    stamps it in the same write — and is skipped rather than treated as
    infinitely old, because "no deletion time" must never read as "purge now".
    """
    cutoff = now - timedelta(days=retention)
    rows = await session.exec(
        select(Guild.id, Guild.status_changed_at)
        .where(
            Guild.status == GuildStatus.deleted.value,
            Guild.status_changed_at.is_not(None),
            Guild.status_changed_at <= cutoff,
        )
        .order_by(Guild.status_changed_at.asc())
    )
    return [row[0] for row in rows]


async def _purge_one(session: AsyncSession, guild_id: int, *, retention: int) -> None:
    """Destroy one guild. Mirrors the sequence the delete endpoint used to run.

    The row goes first and is committed on its own: that is the reliable part,
    and it is what makes the guild gone. The schema drop and blob purge follow;
    if they fail, :func:`reclaim_orphaned_guilds` drops the schema on the next
    pass, whereas a failed cleanup that rolled back the row would leave the
    guild due for purge forever.
    """
    await audit_service.record(
        session,
        event_type=AuditEventType.GUILD_PURGED,
        actor_user_id=None,
        guild_id=guild_id,
        target_type="guild",
        target_id=guild_id,
        detail={"retention_days": retention},
    )
    await session.exec(delete(Guild).where(Guild.id == guild_id))
    await session.commit()

    # These live on other connections, so they go after the commit that made
    # the purge real.
    await app_refs.forget_guild(guild_id=guild_id)
    try:
        await deprovision_guild(guild_id)
    except Exception:
        logger.exception(
            "guild purge: schema/blob cleanup for guild %s failed "
            "(row already deleted; reclaimed on the next pass)",
            guild_id,
        )


async def purge_due_guilds(session: AsyncSession, *, now: datetime) -> int:
    """One pass. Returns how many guilds were destroyed.

    Split out from the loop entry point so tests can drive it with the test
    session and a chosen ``now``.
    """
    await set_rls_context(session)
    retention = await retention_days(session)
    if retention is None:
        # This deployment keeps deleted communities. Nothing is ever destroyed
        # on a timer; restoring and purging are both somebody's decision.
        return 0
    guild_ids = await _due_guild_ids(session, now=now, retention=retention)
    for guild_id in guild_ids:
        # ids collide across schemas, so clear the identity map between guilds.
        session.expunge_all()
        await _purge_one(session, guild_id, retention=retention)
    if guild_ids:
        logger.info("guild purge: destroyed %d guild(s)", len(guild_ids))
    return len(guild_ids)


async def _orphaned_guild_ids(session: AsyncSession) -> list[int]:
    """Guild schemas with no ``public.guilds`` row behind them.

    Every path that creates a guild commits its row before provisioning the
    schema, and every path that removes one deletes the row before dropping
    the schema, so a schema without a row is one whose teardown did not finish.
    """
    rows = await session.exec(
        text(
            "SELECT substring(n.nspname FROM 7)::int AS guild_id "
            "FROM pg_namespace n "
            "WHERE n.nspname ~ '^guild_[0-9]+$' "
            "AND NOT EXISTS ("
            "SELECT 1 FROM public.guilds g "
            "WHERE g.id = substring(n.nspname FROM 7)::int"
            ") "
            "ORDER BY 1"
        )
    )
    return [row[0] for row in rows]


async def reclaim_orphaned_guilds(session: AsyncSession) -> int:
    """Drop the schema, roles and blobs of every guild whose row is gone.

    Runs whatever the retention setting says: the window governs deleted
    communities that still have a row, and these have none. Returns how many
    were reclaimed; one that fails again is logged and retried next pass.
    """
    await set_rls_context(session)
    guild_ids = await _orphaned_guild_ids(session)
    # End the read before the drops, which run on the provisioning engine.
    await session.commit()
    reclaimed = 0
    for guild_id in guild_ids:
        try:
            await deprovision_guild(guild_id)
        except Exception:
            logger.exception(
                "guild purge: reclaiming orphaned schema for guild %s failed",
                guild_id,
            )
            continue
        reclaimed += 1
    if reclaimed:
        logger.info("guild purge: reclaimed %d orphaned guild schema(s)", reclaimed)
    return reclaimed


async def process_guild_purges() -> None:
    """One pass of the guild-purge loop. Idempotent and safe to run on a
    schedule even when nothing is due."""
    now = datetime.now(timezone.utc)
    async with SystemSessionLocal() as session:
        await delete_expired_holds(session, now=now)
        await purge_due_guilds(session, now=now)
        await reclaim_orphaned_guilds(session)
