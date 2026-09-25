"""Auto-purge background worker for trashed entities past their retention.

Polled by ``background_tasks._loop_worker`` once an hour. Connects via
``SystemSessionLocal`` (the ``app_admin`` login) and routes into each guild's
schema on the system engine, whose login the policies' system leg names — it clears
the ``soft_delete_admin_purge`` RESTRICTIVE FOR DELETE guard (and the
initiative-member policies), since SET ROLE into ``guild_<id>`` drops the
``app_admin`` (BYPASSRLS drops on SET ROLE) and routes into each guild as a
guild admin. See ``_purge_all_guilds``.

Each table's due rows are purged together, parents first, through the same
``hard_purge_entities`` the trash can's purge button uses: documents and
pictures take their stored files with them, and descendants go before the rows
they hang off.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlmodel import select

from app.core.audit_events import AuditEventType
from app.db.session import SystemSessionLocal, set_rls_context
from app.db.soft_delete_filter import SOFT_DELETE_MODELS, select_including_deleted
from app.models.platform.guild import Guild, GuildStatus
from app.services import audit as audit_service
from app.services.storage import get_guild_storage
from app.services.tenant.attachments import release_unclaimed_pasted_images
from app.services.tenant.lifecycle_tree import parents_first
from app.services.tenant.soft_delete import hard_purge_entities


logger = logging.getLogger(__name__)


PURGE_POLL_SECONDS = 3600


#: Every soft-deletable model, parents before children, so a row whose
#: retention has elapsed takes its descendants with it and the later passes find
#: them gone.
_PURGE_TOP_DOWN = parents_first(SOFT_DELETE_MODELS)


def _entity_type(model: type) -> str:
    """The trash-can name for a model — ``CounterGroup`` → ``counter_group``."""
    name = model.__name__
    parts: list[str] = []
    for index, char in enumerate(name):
        if char.isupper() and index:
            parts.append("_")
        parts.append(char.lower())
    return "".join(parts)


async def _run_purge_pass(
    session, *, now: datetime, guild_id: int | None = None
) -> None:
    """Inner loop: walks _PURGE_TOP_DOWN once on the supplied session.
    Caller commits. Factored out so tests can drive it with their own
    session against the test DB.

    With ``guild_id``, a pass that purged anything records it once, with the
    count per entity type. The session is routed into the guild with no
    account behind it, so the record carries no actor."""
    purged: dict[str, int] = {}
    for model in _PURGE_TOP_DOWN:
        # A row an earlier pass took with its parent is already gone from the
        # database, so it is not found here.
        stmt = (
            select_including_deleted(model)
            .where(model.purge_at.is_not(None))
            .where(model.purge_at < now)
        )
        rows = list((await session.exec(stmt)).all())
        if rows:
            await hard_purge_entities(session, rows)
            purged[_entity_type(model)] = len(rows)

    if guild_id is not None and purged:
        await audit_service.record(
            session,
            event_type=AuditEventType.TRASH_PURGED,
            actor_user_id=None,
            guild_id=guild_id,
            detail={"via": "sweep", "counts": purged},
        )


async def _purge_all_guilds(session, *, now: datetime) -> None:
    """Run the purge pass once in every guild's schema.

    Each guild's trashed rows live in its own schema, so the worker has to visit
    them all. Trash purge is system maintenance with full authority over the
    guild, so it routes into each guild's schema AS A GUILD ADMIN
    (the system leg, keyed on the connection's own login). That leg clears both the
    initiative-member policies and the ``soft_delete_admin_purge`` RESTRICTIVE
    guard on the soft-delete tables — ``SET ROLE`` drops the system engine's
    BYPASSRLS, so the admin context is what lets the hard deletes through.
    Guilds are enumerated on the system engine first; each schema gets its
    own committed pass. Split out so tests can drive it with the test session.
    """
    await set_rls_context(session)
    # Only ACTIVE guilds are purged. A read_only or suspended guild is frozen —
    # a nonpayment/moderation hold must not keep destroying trashed data while
    # it is unresolved (data ownership / legal). Retention resumes (with the
    # original purge_at stamps) when the guild returns to active.
    guild_ids = list(
        await session.exec(
            select(Guild.id)
            .where(Guild.status == GuildStatus.active.value)
            .order_by(Guild.id.asc())
        )
    )
    for guild_id in guild_ids:
        # ids collide across schemas, so clear the identity map between guilds.
        session.expunge_all()
        await set_rls_context(session, guild_id=guild_id)
        await _run_purge_pass(session, now=now, guild_id=guild_id)
        # Pictures pasted and never saved — the tab was closed rather than
        # left — go once their grace period is over.
        unclaimed = await release_unclaimed_pasted_images(session, now=now)
        await session.commit()
        storage = get_guild_storage(guild_id)
        for name in unclaimed:
            storage.delete(name)


async def process_trash_purges() -> None:
    """One pass of the auto-purge loop across every guild schema. Idempotent and
    safe to run on a schedule even when nothing is due.

    Goes through ``hard_purge_entities`` rather than a bare
    ``DELETE … WHERE purge_at < now()``, so that:
    1. ``Document`` upload cleanup (blobs + Upload rows) runs before each
       Document is deleted.
    2. Descendants go first — most keys between these tables do not cascade
       in the database, so a bare delete of a parent would fail on them.
    """
    now = datetime.now(timezone.utc)
    async with SystemSessionLocal() as session:
        await _purge_all_guilds(session, now=now)
