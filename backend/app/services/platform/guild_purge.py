"""Destroy guilds whose retention window has run out.

Deleting a guild no longer destroys it: it moves to ``CommunityStatus.deleted``
and keeps everything — the shared rows, the ``guild_<id>`` schema, the stored
blobs — so a platform operator can put the community back. This worker is what
eventually does the destroying, and it does exactly what the delete used to do
inline: remove the shared guild row (whose ``ON DELETE CASCADE`` clears the
roster), forget the identities its plug-ins knew its members by, then drop the
schema and purge the blobs. Each pass then reclaims any ``guild_<id>`` schema
whose row is already gone — a teardown that deleted the row but did not finish
dropping the schema, here or where a guild's creation was rolled back.

Before any of that, each pass deletes the communities whose hold has run out:
one left ``on_hold`` for longer than the deployment's hold window moves to
``deleted`` exactly as a deletion from its danger zone would, and the
retention window then starts like any other.

Polled by ``background_tasks.Loop`` once an hour on ``SystemSessionLocal``
(the ``app_admin`` login). It works on ``public.guilds``; the one thing it does
inside a guild's schema, deleting a held community's plug-in connections, runs on
a system session from that community's cohort. The schema is dropped wholesale
on the provisioning engine.
"""

from __future__ import annotations

from datetime import datetime, timezone
import logging

from sqlalchemy import text
from sqlmodel import delete
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.audit_events import AuditEventType
from app.db import cohorts
from app.db.guild_migrations import GUILD_SCHEMA_REGEX
from app.db.schema_provisioning import deprovision_guild
from app.db.session import SystemSessionLocal, set_rls_context
from app.models.platform.guild import Guild
from app.services import audit as audit_service
from app.services.marketplace import plugin_refs
from app.services.platform.retention import COMMUNITY_DELETION, COMMUNITY_HOLD
from app.db.request_context import SystemGuild, Unattributed


logger = logging.getLogger(__name__)


GUILD_PURGE_POLL_SECONDS = 3600


async def _delete_expired_hold(session: AsyncSession, guild: Guild, _days: int) -> None:
    """Delete one community whose hold has run out. Mirrors the danger-zone
    delete: its plug-ins let go, the status moves to ``deleted``, the seat is
    written to, and billing is told to read what happened.

    Runs in the transaction that claimed the row and commits it, so a hold
    lifted while the pass runs leaves the community exactly as it was. Its
    plug-in connections are deleted in its own schema first, under that claim,
    so a status write that fails leaves a held community without them, which
    the next pass deletes. Nobody asked for this deletion, so the roster stays
    whatever its size.
    """
    from app.services import email as email_service
    from app.services.platform import billing_ping
    from app.services.platform import guilds as guilds_service
    from app.services.tenant import plugin_connections as plugin_connections_service
    from app.services.tenant import plugin_revocation as plugin_revocation_service

    guild_id = guild.id
    async with cohorts.system_session(guild_id) as guild_session:
        await set_rls_context(guild_session, SystemGuild(guild_id))
        await plugin_connections_service.delete_guild_connections(guild_session)
        await guild_session.commit()
        revocations = plugin_revocation_service.drain_revocations(guild_session)

    try:
        notice = await guilds_service.soft_delete_guild(
            session, guild, via="hold_expired", keep_roster=True
        )
        await session.commit()
    finally:
        # The connections are gone either way, so the plug-ins are told either way.
        await plugin_revocation_service.dispatch_revocations(revocations)

    await email_service.announce_community_deleted(session, notice)
    # These live on other connections, so they go after the commit that made
    # the deletion real.
    await plugin_refs.forget_guild(guild_id=guild_id, keep_billing=True)
    billing_ping.notify_lifecycle_changed(guild_id)


async def delete_expired_holds(session: AsyncSession, *, now: datetime) -> int:
    """One pass of :data:`~app.services.platform.retention.COMMUNITY_HOLD`.
    Returns how many communities were deleted.

    Counted from ``status_changed_at``, which is stamped when a community is
    put on hold and not again while it stays there, so a hold written twice
    does not restart the clock.
    """
    return await COMMUNITY_HOLD.sweep(session, now=now, act=_delete_expired_hold)


async def _destroy(session: AsyncSession, guild: Guild, days: int) -> None:
    """Destroy one guild. Mirrors the sequence the delete endpoint used to run.

    The row goes first, recorded and committed in the transaction that claimed
    it: that is the reliable part, and it is what makes the guild gone. The
    schema drop and blob purge follow; if they fail,
    :func:`reclaim_orphaned_guilds` drops the schema on the next pass, whereas
    a failed cleanup that rolled back the row would leave the guild due for
    purge forever.
    """
    guild_id = guild.id
    await session.exec(delete(Guild).where(Guild.id == guild_id))
    await audit_service.record(
        session,
        event_type=AuditEventType.GUILD_PURGED,
        actor_user_id=None,
        guild_id=guild_id,
        target_type="guild",
        target_id=guild_id,
        detail={"retention_days": days},
    )
    await session.commit()

    # These live on other connections, so they go after the commit that made
    # the purge real.
    await plugin_refs.forget_guild(guild_id=guild_id)
    try:
        await deprovision_guild(guild_id)
    except Exception:
        logger.exception(
            "guild purge: schema/blob cleanup for guild %s failed "
            "(row already deleted; reclaimed on the next pass)",
            guild_id,
        )


async def purge_due_guilds(session: AsyncSession, *, now: datetime) -> int:
    """One pass of :data:`~app.services.platform.retention.COMMUNITY_DELETION`.
    Returns how many guilds were destroyed.

    Split out from the loop entry point so tests can drive it with the test
    session and a chosen ``now``.
    """
    return await COMMUNITY_DELETION.sweep(session, now=now, act=_destroy)


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
            "WHERE n.nspname ~ :pat "
            "AND NOT EXISTS ("
            "SELECT 1 FROM public.guilds g "
            "WHERE g.id = substring(n.nspname FROM 7)::int"
            ") "
            "ORDER BY 1"
        ),
        params={"pat": GUILD_SCHEMA_REGEX},
    )
    return [row[0] for row in rows]


async def reclaim_orphaned_guilds(session: AsyncSession) -> int:
    """Drop the schema, roles and blobs of every guild whose row is gone.

    Runs whatever the retention setting says: the window governs deleted
    communities that still have a row, and these have none. Returns how many
    were reclaimed; one that fails again is logged and retried next pass.
    """
    await set_rls_context(session, Unattributed())
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
