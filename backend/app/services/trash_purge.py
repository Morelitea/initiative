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

from sqlalchemy import delete as sa_delete

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
from app.services.attachments import purge_document_uploads


logger = logging.getLogger(__name__)


PURGE_POLL_SECONDS = 3600


# Tables we can bulk-delete without per-row cleanup. Order matters only for
# log readability; FK cascades handle child rows automatically.
_BULK_PURGE_MODELS = (
    Comment,
    Task,
    Project,
    Queue,
    QueueItem,
    Tag,
    CalendarEvent,
)


async def process_trash_purges() -> None:
    """One pass of the auto-purge loop. Idempotent and safe to run on a
    schedule even when nothing is due."""
    now = datetime.now(timezone.utc)

    async with AdminSessionLocal() as session:
        # 1. Documents (and Initiatives that cascade to Documents) need
        #    per-row upload cleanup before we DELETE them.
        await _purge_documents_with_uploads(session, now=now)
        await _purge_initiatives_with_descendant_uploads(session, now=now)

        # 2. Bulk DELETE the remaining tables. Their descendants (subtasks,
        #    permissions, junction rows) fall via FK CASCADE.
        for model in _BULK_PURGE_MODELS:
            stmt = sa_delete(model).where(
                model.purge_at.is_not(None),
                model.purge_at < now,
            )
            await session.exec(stmt)

        await session.commit()


async def _purge_documents_with_uploads(session, *, now: datetime) -> None:
    """Hard-purge Documents whose retention window has elapsed, running
    upload cleanup first. Documents that were cascaded under an Initiative
    are handled by ``_purge_initiatives_with_descendant_uploads`` to keep
    the Document row alive while we extract URL references."""
    stmt = (
        select_including_deleted(Document)
        .where(Document.purge_at.is_not(None))
        .where(Document.purge_at < now)
    )
    result = await session.exec(stmt)
    docs = list(result.all())
    if not docs:
        return
    await purge_document_uploads(session, docs)
    for d in docs:
        await session.delete(d)


async def _purge_initiatives_with_descendant_uploads(session, *, now: datetime) -> None:
    """Hard-purge Initiatives whose retention window has elapsed. Before
    deleting the Initiative, run upload cleanup for every Document scoped
    to it (the FK CASCADE would otherwise drop the Documents without
    cleaning up their blobs)."""
    stmt = (
        select_including_deleted(Initiative)
        .where(Initiative.purge_at.is_not(None))
        .where(Initiative.purge_at < now)
    )
    result = await session.exec(stmt)
    initiatives = list(result.all())
    if not initiatives:
        return
    for initiative in initiatives:
        doc_stmt = (
            select_including_deleted(Document)
            .where(Document.initiative_id == initiative.id)
        )
        doc_result = await session.exec(doc_stmt)
        docs = list(doc_result.all())
        if docs:
            await purge_document_uploads(session, docs)
        await session.delete(initiative)
