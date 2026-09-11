"""Generic soft-delete / restore / hard-purge service.

Single source of truth for the trash lifecycle on every entity that inherits
``SoftDeleteMixin``. Cascading is explicit (not magical): the
``CASCADE_CHILDREN`` registry below enumerates which child collections to
stamp when a parent is soft-deleted, and the inverse on restore.

Restore does not ask who should own the entity. Ownership is recorded in
``resource_grants`` and never sits with someone who has left the guild, so a
restored row is owned by whoever owns it or by nobody — the same as it was while
in the trash. The columns restore used to reassign name the *author*, which is a
historical fact and not reassignable at all.

A trashed row is read-only at the database — see ``app.db.frozen`` — so both
walks here are ordered against that: a stamp goes deepest-first, a restore
shallowest-first, and each level is flushed before the next so the order is the
one the database sees rather than the one the unit of work picks.

Hard-purge is admin-only at the DB layer on EVERY soft-delete table: the
``soft_delete_admin_purge`` RESTRICTIVE FOR DELETE policy (rendered by
``app.db.guild_ddl`` from the SoftDeleteMixin subclasses) admits only a routed
guild admin, so a non-admin DELETE is refused by Postgres, not just by app code.
The two
guild-level soft-delete tables (initiatives, tags) have RLS enabled solely to host
that guard — not a membership gate (initiative is the gate; guilds gate at the
schema). For Documents (and Initiatives whose cascade includes Documents), upload
cleanup runs before the DELETE so blobs on disk and ``Upload`` rows pinned only by
the doomed documents are also removed.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlmodel.ext.asyncio.session import AsyncSession

from sqlalchemy import text

from app.db.frozen import PURGE_GUC
from app.db.soft_delete_filter import select_including_deleted
from app.models.tenant._mixins import SoftDeleteMixin
from app.models.tenant.calendar import Calendar
from app.models.tenant.calendar_event import CalendarEvent
from app.models.tenant.comment import Comment
from app.models.tenant.dashboard import Dashboard
from app.models.tenant.document import Document
from app.models.tenant.initiative import Initiative
from app.models.tenant.project import Project
from app.models.tenant.counter import Counter, CounterGroup
from app.models.tenant.post import Post
from app.models.tenant.gallery import Gallery, GalleryImage
from app.models.tenant.queue import Queue, QueueItem
from app.models.tenant.task import Task


# parent_model -> list of (child_model, fk_column_name)
# Keep in sync with the "owns" relationships across initiative-scoped tables.
# Tag is omitted intentionally — tags are guild-level, not nested under any
# of these parents.
CASCADE_CHILDREN: dict[type, list[tuple[type, str]]] = {
    Initiative: [
        (Project, "initiative_id"),
        (Document, "initiative_id"),
        (Queue, "initiative_id"),
        (Calendar, "initiative_id"),
        (Dashboard, "initiative_id"),
        (Post, "initiative_id"),
        (Gallery, "initiative_id"),
        (CounterGroup, "initiative_id"),
    ],
    Project: [(Task, "project_id")],
    Calendar: [(CalendarEvent, "calendar_id")],
    Document: [(Comment, "document_id")],
    Post: [(Comment, "post_id")],
    Gallery: [(GalleryImage, "gallery_id"), (Comment, "gallery_id")],
    Task: [(Comment, "task_id")],
    Queue: [(QueueItem, "queue_id")],
    CounterGroup: [(Counter, "counter_group_id")],
    Comment: [(Comment, "parent_comment_id")],
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _compute_purge_at(
    deleted_at: datetime, retention_days: Optional[int]
) -> Optional[datetime]:
    if retention_days is None:
        return None
    return deleted_at + timedelta(days=retention_days)


async def _descendant_levels(
    session: AsyncSession,
    parent: SoftDeleteMixin,
    *,
    match_deleted_at: Optional[datetime],
) -> list[list[SoftDeleteMixin]]:
    """Every descendant of ``parent``, grouped by how far down it sits.

    Breadth-first over ``CASCADE_CHILDREN``: level 0 is the direct children,
    level 1 their children, and so on. The caller walks the levels in whichever
    direction its write needs — see the ordering note on the two callers below.

    ``match_deleted_at`` picks the set: ``None`` takes the ACTIVE descendants
    (what a soft-delete stamps), a timestamp takes the ones stamped by that same
    soft-delete (what a restore brings back), so an independently-trashed child
    keeps its own ``deleted_at`` either way.
    """
    levels: list[list[SoftDeleteMixin]] = []
    frontier: list[SoftDeleteMixin] = [parent]
    while frontier:
        level: list[SoftDeleteMixin] = []
        for node in frontier:
            for child_model, fk_col in CASCADE_CHILDREN.get(type(node), []):
                fk = getattr(child_model, fk_col)
                stmt = select_including_deleted(child_model).where(fk == node.id)
                if match_deleted_at is None:
                    stmt = stmt.where(child_model.deleted_at.is_(None))
                else:
                    stmt = stmt.where(child_model.deleted_at == match_deleted_at)
                result = await session.exec(stmt)
                level.extend(result.all())
        if not level:
            break
        levels.append(level)
        frontier = level
    return levels


async def soft_delete_entity(
    session: AsyncSession,
    entity: SoftDeleteMixin,
    *,
    deleted_by_user_id: Optional[int],
    retention_days: Optional[int],
) -> None:
    """Stamp the entity and every active descendant as soft-deleted.

    Idempotent: re-stamping an already-soft-deleted entity is a no-op so
    callers can safely retry. The caller is responsible for committing.
    """
    if entity.deleted_at is not None:
        return
    deleted_at = _utc_now()
    purge_at = _compute_purge_at(deleted_at, retention_days)

    # Deepest first, with a flush per level. A trashed row freezes everything
    # under it at the database, so a child written after its parent was stamped
    # would be refused — and the unit of work orders UPDATEs by mapper, not by
    # the order they were added, so the levels are flushed explicitly rather
    # than assumed. Collected before the entity is stamped, while the walk's own
    # queries still see an untouched tree.
    levels = await _descendant_levels(session, entity, match_deleted_at=None)
    for level in reversed(levels):
        for child in level:
            child.deleted_at = deleted_at
            child.deleted_by = deleted_by_user_id
            child.purge_at = purge_at
            session.add(child)
        await session.flush()

    entity.deleted_at = deleted_at
    entity.deleted_by = deleted_by_user_id
    entity.purge_at = purge_at
    session.add(entity)
    await session.flush()


async def _resolve_initiative_scope(
    session: AsyncSession,
    entity: SoftDeleteMixin,
) -> Optional[int]:
    """Return the initiative_id this entity is scoped to, walking up the
    parent chain when necessary. None for guild-level entities (Tag) or
    when the parent row can't be resolved."""
    # Direct initiative_id on the entity itself.
    if (
        hasattr(entity, "initiative_id")
        and getattr(entity, "initiative_id") is not None
    ):
        return int(entity.initiative_id)
    # Project-scoped → look up project.initiative_id.
    if isinstance(entity, Task) and entity.project_id is not None:
        stmt = select_including_deleted(Project.initiative_id).where(
            Project.id == entity.project_id
        )
        result = await session.exec(stmt)
        row = result.one_or_none()
        return int(row) if row is not None else None
    # Calendar-scoped → look up calendar.initiative_id.
    if isinstance(entity, CalendarEvent) and entity.calendar_id is not None:
        stmt = select_including_deleted(Calendar.initiative_id).where(
            Calendar.id == entity.calendar_id
        )
        result = await session.exec(stmt)
        row = result.one_or_none()
        return int(row) if row is not None else None
    # Comments can hang off either a task or a document.
    if isinstance(entity, Comment):
        if entity.task_id is not None:
            stmt = (
                select_including_deleted(Project.initiative_id)
                .join(Task, Task.project_id == Project.id)
                .where(Task.id == entity.task_id)
            )
            result = await session.exec(stmt)
            row = result.one_or_none()
            return int(row) if row is not None else None
        if entity.document_id is not None:
            stmt = select_including_deleted(Document.initiative_id).where(
                Document.id == entity.document_id
            )
            result = await session.exec(stmt)
            row = result.one_or_none()
            return int(row) if row is not None else None
    return None


async def restore_entity(
    session: AsyncSession,
    entity: SoftDeleteMixin,
) -> None:
    """Restore the entity and its cascaded descendants.

    Idempotent on already-active rows. Caller commits.
    """
    if entity.deleted_at is None:
        return

    matching_deleted_at = entity.deleted_at
    # The mirror of the stamp above: shallowest first, so a child is never
    # written while its parent is still trashed. Collected before anything is
    # cleared, because the set is defined by the timestamp being cleared.
    levels = await _descendant_levels(
        session, entity, match_deleted_at=matching_deleted_at
    )

    entity.deleted_at = None
    entity.deleted_by = None
    entity.purge_at = None
    session.add(entity)
    await session.flush()

    for level in levels:
        for child in level:
            child.deleted_at = None
            child.deleted_by = None
            child.purge_at = None
            session.add(child)
        await session.flush()


async def _purge_relationships(
    session: AsyncSession, doomed: list[SoftDeleteMixin]
) -> None:
    """Drop every edge naming one of these, whichever end it names them on."""
    from app.core.relationships import ENDPOINT_KINDS
    from app.core.search import SearchEntityType
    from app.services.tenant import relationships

    # Derived from the endpoint registry rather than a second list of model
    # classes: a kind that can sit on an edge is a kind whose table is named
    # there, and the model already knows its table.
    kind_by_table = {endpoint.table: kind for kind, endpoint in ENDPOINT_KINDS.items()}

    by_kind: dict[SearchEntityType, list[int]] = {}
    for row in doomed:
        kind = kind_by_table.get(getattr(type(row), "__tablename__", ""))
        if kind is None or getattr(row, "id", None) is None:
            continue
        by_kind.setdefault(kind, []).append(row.id)

    for kind, ids in by_kind.items():
        await relationships.purge_for_entities(session, kind, ids)


async def _gather_descendants(
    session: AsyncSession,
    parent: SoftDeleteMixin,
) -> list[SoftDeleteMixin]:
    """Walk CASCADE_CHILDREN in pre-order and return every descendant of
    ``parent`` (active OR soft-deleted) in dependency order — children
    before grandchildren. Used by ``hard_purge_entity`` to issue explicit
    deletes since most FKs in this codebase use ORM cascade (which doesn't
    fire unless the rows are loaded) rather than DB-level ON DELETE CASCADE.
    """
    out: list[SoftDeleteMixin] = []
    for child_model, fk_col in CASCADE_CHILDREN.get(type(parent), []):
        fk = getattr(child_model, fk_col)
        stmt = select_including_deleted(child_model).where(fk == parent.id)
        result = await session.exec(stmt)
        for child in result.all():
            out.append(child)
            out.extend(await _gather_descendants(session, child))
    return out


async def hard_purge_entity(
    session: AsyncSession,
    entity: SoftDeleteMixin,
) -> None:
    """Hard-delete the entity and every descendant.

    The caller's ``session`` must be able to clear the RESTRICTIVE FOR DELETE
    policies on these tables — either a routed **guild-admin** RLS session (the
    interactive purge endpoint) or a guild-admin-routed ``app_admin`` session (the
    background auto-purge worker, which has no guild context). The caller is also
    responsible for locking the target against a concurrent restore and for
    committing.

    Descendants are walked via the same CASCADE_CHILDREN registry the
    soft-delete path uses, then deleted in reverse (grandchildren first)
    so DB-level FK constraints don't fire. For Documents anywhere in the
    descendant set, upload cleanup runs before the DELETEs so blobs on
    disk and ``Upload`` rows pinned only by the doomed documents are also
    removed.
    """
    from app.services.tenant.documents import unresolve_wikilinks_to_document
    from app.services.tenant.attachments import (
        purge_document_uploads,
        purge_gallery_image_uploads,
    )
    from app.services.tenant.reactions import purge_comment_reactions

    # Purge is the one lifecycle step that writes frozen content instead of only
    # removing it — the wikilink unresolve below reaches documents that are
    # themselves in the trash. Transaction-local (see app.db.frozen.PURGE_GUC).
    await session.exec(
        text("SELECT set_config(:name, 'true', true)").bindparams(name=PURGE_GUC)
    )

    descendants = await _gather_descendants(session, entity)
    all_doomed: list[SoftDeleteMixin] = [entity, *descendants]

    # Reactions name their target polymorphically, so no foreign key carries
    # them out with the comment. Cleared explicitly, before the row goes.
    doomed_comments = [c for c in all_doomed if isinstance(c, Comment)]
    if doomed_comments:
        await purge_comment_reactions(session, doomed_comments)

    # Edges name both ends polymorphically, so nothing carries them out with
    # the thing they connect. Tombstones go too: what one remembers is a link
    # between two things, and one of them is about to stop existing.
    await _purge_relationships(session, all_doomed)

    # A picture's blobs — every version and its thumbnail — go with it, the
    # way a file document's do.
    doomed_images = [i for i in all_doomed if isinstance(i, GalleryImage)]
    if doomed_images:
        await purge_gallery_image_uploads(session, doomed_images)

    doomed_documents = [d for d in all_doomed if isinstance(d, Document)]
    if doomed_documents:
        await purge_document_uploads(session, doomed_documents)
        # Wikilinks in surviving documents that point at a doomed one must be
        # unresolved (documentId → null) before the row disappears, or they'd
        # dangle forever. Runs before the DELETEs — the document_links rows
        # are still present to find the linking documents.
        for doc in doomed_documents:
            await unresolve_wikilinks_to_document(session, deleted_document_id=doc.id)

    # Reverse so we delete leaves before parents — needed because most FKs
    # in this codebase don't use DB-level ON DELETE CASCADE.
    for row in reversed(all_doomed):
        await session.delete(row)
