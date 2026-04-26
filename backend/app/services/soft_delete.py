"""Generic soft-delete / restore / hard-purge service.

Single source of truth for the trash lifecycle on every entity that inherits
``SoftDeleteMixin``. Cascading is explicit (not magical): the
``CASCADE_CHILDREN`` registry below enumerates which child collections to
stamp when a parent is soft-deleted, and the inverse on restore.

Restoring an entity whose owning user has since left the relevant scope
(initiative for Project/Task/Document/Comment/Queue/CalendarEvent) returns
``RestoreResult(needs_reassignment=True, valid_owner_ids=[...])``. The
endpoint surfaces this as 409 + the id list; the client opens a picker and
resubmits with ``new_owner_id=N`` which the service re-validates and applies
before completing the restore.

Hard-purge is admin-only at the DB layer (``RESTRICTIVE FOR DELETE`` policy
from migration 20260426_0077). For Documents (and Initiatives whose cascade
includes Documents), upload cleanup runs before the DELETE so blobs on disk
and ``Upload`` rows pinned only by the doomed documents are also removed.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db.soft_delete_filter import select_including_deleted
from app.models._mixins import SoftDeleteMixin
from app.models.calendar_event import CalendarEvent
from app.models.comment import Comment
from app.models.document import Document
from app.models.initiative import Initiative, InitiativeMember
from app.models.project import Project
from app.models.queue import Queue, QueueItem
from app.models.task import Task
from app.models.user import User, UserStatus


# parent_model -> list of (child_model, fk_column_name)
# Keep in sync with the "owns" relationships across initiative-scoped tables.
# Tag is omitted intentionally — tags are guild-level, not nested under any
# of these parents.
CASCADE_CHILDREN: dict[type, list[tuple[type, str]]] = {
    Initiative: [
        (Project, "initiative_id"),
        (Document, "initiative_id"),
        (Queue, "initiative_id"),
        (CalendarEvent, "initiative_id"),
    ],
    Project: [(Task, "project_id")],
    Document: [(Comment, "document_id")],
    Task: [(Comment, "task_id")],
    Queue: [(QueueItem, "queue_id")],
    Comment: [(Comment, "parent_comment_id")],
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _compute_purge_at(deleted_at: datetime, retention_days: Optional[int]) -> Optional[datetime]:
    if retention_days is None:
        return None
    return deleted_at + timedelta(days=retention_days)


async def _stamp_descendants(
    session: AsyncSession,
    parent: SoftDeleteMixin,
    *,
    deleted_at: datetime,
    deleted_by: Optional[int],
    purge_at: Optional[datetime],
) -> None:
    """Recursively stamp deleted_at / deleted_by / purge_at on every active
    descendant of ``parent``. Skips already-soft-deleted children so an
    independently-trashed child keeps its own deleted_at."""
    for child_model, fk_col in CASCADE_CHILDREN.get(type(parent), []):
        fk = getattr(child_model, fk_col)
        stmt = (
            select_including_deleted(child_model)
            .where(fk == parent.id)
            .where(child_model.deleted_at.is_(None))
        )
        result = await session.exec(stmt)
        for child in result.all():
            child.deleted_at = deleted_at
            child.deleted_by = deleted_by
            child.purge_at = purge_at
            session.add(child)
            await _stamp_descendants(
                session,
                child,
                deleted_at=deleted_at,
                deleted_by=deleted_by,
                purge_at=purge_at,
            )


async def _unstamp_descendants(
    session: AsyncSession,
    parent: SoftDeleteMixin,
    *,
    matching_deleted_at: datetime,
) -> None:
    """Inverse of _stamp_descendants. Restores only descendants whose
    deleted_at == matching_deleted_at, so that children which were
    independently soft-deleted (different timestamp) remain in trash."""
    for child_model, fk_col in CASCADE_CHILDREN.get(type(parent), []):
        fk = getattr(child_model, fk_col)
        stmt = (
            select_including_deleted(child_model)
            .where(fk == parent.id)
            .where(child_model.deleted_at == matching_deleted_at)
        )
        result = await session.exec(stmt)
        for child in result.all():
            child.deleted_at = None
            child.deleted_by = None
            child.purge_at = None
            session.add(child)
            await _unstamp_descendants(
                session,
                child,
                matching_deleted_at=matching_deleted_at,
            )


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
    entity.deleted_at = deleted_at
    entity.deleted_by = deleted_by_user_id
    entity.purge_at = purge_at
    session.add(entity)
    await _stamp_descendants(
        session,
        entity,
        deleted_at=deleted_at,
        deleted_by=deleted_by_user_id,
        purge_at=purge_at,
    )


@dataclass
class RestoreResult:
    needs_reassignment: bool
    valid_owner_ids: Optional[list[int]] = None


async def _initiative_member_ids(
    session: AsyncSession,
    *,
    initiative_id: int,
) -> list[int]:
    """Active user ids that are still members of the initiative."""
    stmt = (
        select(User.id)
        .join(InitiativeMember, InitiativeMember.user_id == User.id)
        .where(InitiativeMember.initiative_id == initiative_id)
        .where(User.status == UserStatus.active)
    )
    result = await session.exec(stmt)
    return list(result.all())


async def _resolve_initiative_scope(
    session: AsyncSession,
    entity: SoftDeleteMixin,
) -> Optional[int]:
    """Return the initiative_id this entity is scoped to, walking up the
    parent chain when necessary. None for guild-level entities (Tag) or
    when the parent row can't be resolved."""
    # Direct initiative_id on the entity itself.
    if hasattr(entity, "initiative_id") and getattr(entity, "initiative_id") is not None:
        return int(entity.initiative_id)
    # Project-scoped → look up project.initiative_id.
    if isinstance(entity, Task) and entity.project_id is not None:
        stmt = select_including_deleted(Project.initiative_id).where(Project.id == entity.project_id)
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
    *,
    new_owner_id: Optional[int] = None,
) -> RestoreResult:
    """Restore the entity and its cascaded descendants.

    When ``owner_field()`` is set and the current owner is no longer an
    active member of the relevant initiative scope, return
    ``RestoreResult(needs_reassignment=True, valid_owner_ids=...)`` instead
    of restoring; the endpoint surfaces this as 409 and the client picks a
    new owner. If ``new_owner_id`` is supplied it must be in the valid set
    (otherwise ``ValueError("TRASH_INVALID_OWNER")``); the entity's owner
    column is updated before the restore.

    Idempotent on already-active rows. Caller commits.
    """
    if entity.deleted_at is None:
        return RestoreResult(needs_reassignment=False)

    owner_field = type(entity).owner_field()
    if owner_field is not None:
        current_owner_id = getattr(entity, owner_field)
        scope_initiative_id = await _resolve_initiative_scope(session, entity)
        if scope_initiative_id is not None:
            valid_ids = await _initiative_member_ids(session, initiative_id=scope_initiative_id)
            if new_owner_id is not None:
                if new_owner_id not in valid_ids:
                    raise ValueError("TRASH_INVALID_OWNER")
                setattr(entity, owner_field, new_owner_id)
            elif current_owner_id not in valid_ids:
                return RestoreResult(needs_reassignment=True, valid_owner_ids=valid_ids)

    matching_deleted_at = entity.deleted_at
    entity.deleted_at = None
    entity.deleted_by = None
    entity.purge_at = None
    session.add(entity)
    await _unstamp_descendants(
        session,
        entity,
        matching_deleted_at=matching_deleted_at,
    )
    return RestoreResult(needs_reassignment=False)


async def hard_purge_entity(
    admin_session: AsyncSession,
    entity: SoftDeleteMixin,
) -> None:
    """Hard-delete the entity. Caller must use AdminSessionDep (BYPASSRLS)
    because the in-app ``app_user`` role's RESTRICTIVE DELETE policy denies
    DELETEs except for guild-admin sessions.

    For Documents (and Initiative cascades that include Documents), upload
    cleanup runs first so blobs on disk and ``Upload`` rows pinned only by
    the doomed documents are also removed. The remaining FK CASCADEs at
    the DB layer take care of children (tasks/comments/permissions/etc).

    Caller commits.
    """
    from app.services.attachments import purge_document_uploads

    doomed_documents: list[Document] = []
    if isinstance(entity, Document):
        doomed_documents.append(entity)
    elif isinstance(entity, Initiative):
        stmt = select_including_deleted(Document).where(Document.initiative_id == entity.id)
        result = await admin_session.exec(stmt)
        doomed_documents.extend(result.all())

    if doomed_documents:
        await purge_document_uploads(admin_session, doomed_documents)

    await admin_session.delete(entity)
