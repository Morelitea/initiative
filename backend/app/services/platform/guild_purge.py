"""Destroy guilds whose retention window has run out.

Deleting a guild no longer destroys it: it moves to ``GuildStatus.deleted``
and keeps everything — the shared rows, the ``guild_<id>`` schema, the stored
blobs — so a platform operator can put the community back. This worker is what
eventually does the destroying, and it does exactly what the delete used to do
inline: remove the shared guild row (whose ``ON DELETE CASCADE`` clears the
roster), forget the identities its apps knew its members by, then drop the
schema and purge the blobs.

Polled by ``background_tasks._loop_worker`` once an hour on ``AdminSessionLocal``
(the ``app_admin`` login). It works on ``public.guilds`` alone and never routes
into a guild schema — the schema is dropped wholesale on the provisioning
engine, so there is nothing here to read inside it.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging

from sqlmodel import delete, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.audit_events import AuditEventType
from app.db.schema_provisioning import deprovision_guild
from app.db.session import AdminSessionLocal, set_rls_context
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
    and it is what makes the guild gone. The schema drop and blob purge are
    best-effort cleanup afterwards — an orphaned schema is harmless and is
    reclaimed on the next sweep or the next provision of that id, whereas a
    failed cleanup that rolled back the row would leave the guild due for purge
    forever.
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
            "(row already deleted; orphan is harmless)",
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


async def process_guild_purges() -> None:
    """One pass of the guild-purge loop. Idempotent and safe to run on a
    schedule even when nothing is due."""
    now = datetime.now(timezone.utc)
    async with AdminSessionLocal() as session:
        await purge_due_guilds(session, now=now)
