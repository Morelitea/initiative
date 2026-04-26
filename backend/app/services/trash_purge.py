"""Auto-purge background worker for trashed entities past their retention.

Polled by ``background_tasks._loop_worker`` once an hour. Connects via
``AdminSessionLocal`` (BYPASSRLS role) so the RESTRICTIVE FOR DELETE policy
on every soft-delete-capable table is unaffected.

Documents need per-row treatment because their hard-purge has to clean up
``Upload`` rows + filesystem blobs (both for ``file``-type docs whose Upload
is a 1:1 sibling, and for ``native`` docs whose embedded URLs may have
become orphans). Every other entity table can be bulk-deleted; FK CASCADE
on its descendants takes them too.

Initiative is also handled per-row because cascade-purging an Initiative
takes its Documents with it via FK; the upload cleanup needs to run before
those Documents are deleted.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.db.session import AdminSessionLocal
from app.db.soft_delete_filter import select_including_deleted
from app.models.calendar_event import CalendarEvent
from app.models.comment import Comment
from app.models.document import Document
from app.models.initiative import Initiative
from app.models.project import Project
from app.models.queue import Queue, QueueItem
from app.models.tag import Tag
from app.models.task import Task
from app.services.soft_delete import hard_purge_entity


logger = logging.getLogger(__name__)


PURGE_POLL_SECONDS = 3600


# Top-of-cascade models, in dependency order. We iterate top-down so an
# Initiative whose retention has elapsed takes its Project / Document /
# Queue / CalendarEvent descendants with it via hard_purge_entity, leaving
# the per-entity passes empty for those rows.
_PURGE_TOP_DOWN = (
    Initiative,
    Project,
    Document,
    Task,
    Queue,
    QueueItem,
    Comment,
    Tag,
    CalendarEvent,
)


async def process_trash_purges() -> None:
    """One pass of the auto-purge loop. Idempotent and safe to run on a
    schedule even when nothing is due.

    Uses ``hard_purge_entity`` per row so that:
    1. ``Document`` upload cleanup (blobs + Upload rows) runs before each
       Document is deleted.
    2. ORM-level cascades fire correctly — most FKs in this codebase are
       not declared with DB-level ``ON DELETE CASCADE``, so a bulk
       ``DELETE FROM <table> WHERE purge_at < now()`` would fail on FK
       constraints. ``hard_purge_entity`` walks descendants explicitly.
    """
    now = datetime.now(timezone.utc)

    async with AdminSessionLocal() as session:
        for model in _PURGE_TOP_DOWN:
            stmt = (
                select_including_deleted(model)
                .where(model.purge_at.is_not(None))
                .where(model.purge_at < now)
            )
            result = await session.exec(stmt)
            rows = list(result.all())
            for row in rows:
                # Skip if a parent purge in an earlier iteration of this
                # loop has already swept this row out from under us.
                if row not in session:
                    continue
                await hard_purge_entity(session, row)
        await session.commit()
