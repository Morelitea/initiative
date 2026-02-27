"""Queue service layer — business logic for queue CRUD, turn management, and DAC.

This module handles:
  - Discretionary Access Control (DAC) for queues (mirroring the project/document
    pattern in ``permissions.py``)
  - Queue and queue-item fetching with eager-loaded relationships
  - Turn management (advance, previous, start, stop, reset, set active item)
  - Tag / document / task attachment helpers for queue items
"""

from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import delete as sa_delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlmodel import select

from app.core.messages import QueueMessages
from app.models.document import Document
from app.models.initiative import Initiative, InitiativeMember
from app.models.queue import (
    Queue,
    QueueItem,
    QueueItemDocument,
    QueueItemTag,
    QueueItemTask,
    QueuePermission,
    QueuePermissionLevel,
    QueueRolePermission,
)
from app.models.tag import Tag
from app.models.task import Task
from app.models.user import User
from app.services.permissions import effective_permission_level, role_permission_level


# ---------------------------------------------------------------------------
# DAC constants
# ---------------------------------------------------------------------------

QUEUE_LEVEL_ORDER: dict[QueuePermissionLevel, int] = {
    QueuePermissionLevel.read: 0,
    QueuePermissionLevel.write: 1,
    QueuePermissionLevel.owner: 2,
}


# ---------------------------------------------------------------------------
# Visibility subquery
# ---------------------------------------------------------------------------

def visible_queue_ids_subquery(user_id: int):
    """Return a subquery of queue IDs the user can access.

    Combines user-specific ``QueuePermission`` rows with role-based
    ``QueueRolePermission`` rows matched via ``InitiativeMember``.
    """
    user_perm_subq = (
        select(QueuePermission.queue_id)
        .where(QueuePermission.user_id == user_id)
    )
    role_perm_subq = (
        select(QueueRolePermission.queue_id)
        .join(
            InitiativeMember,
            (InitiativeMember.role_id == QueueRolePermission.initiative_role_id)
            & (InitiativeMember.user_id == user_id),
        )
    )
    return user_perm_subq.union(role_perm_subq)


# ---------------------------------------------------------------------------
# DAC helpers (mirror the project/document pattern in permissions.py)
# ---------------------------------------------------------------------------

def queue_role_permission_level(
    queue: Any,
    user_id: int,
) -> QueuePermissionLevel | None:
    """Get the highest role-based queue permission for a user.

    Reads from eagerly-loaded ``queue.role_permissions`` and
    ``queue.initiative.memberships``.
    """
    role_perms = getattr(queue, "role_permissions", None)
    initiative = getattr(queue, "initiative", None)
    memberships = getattr(initiative, "memberships", None) if initiative else None
    return role_permission_level(role_perms, memberships, user_id, QUEUE_LEVEL_ORDER)


def effective_queue_permission(
    user_level: QueuePermissionLevel | None,
    role_level: QueuePermissionLevel | None,
) -> QueuePermissionLevel | None:
    """MAX of a user-specific and role-based queue permission level."""
    return effective_permission_level(user_level, role_level, QUEUE_LEVEL_ORDER)


def compute_queue_permission(
    queue: Queue,
    user_id: int,
) -> str | None:
    """Compute the effective permission level string for a user on a queue.

    Uses eagerly-loaded relationships (permissions, role_permissions,
    initiative.memberships) so no DB queries are needed.
    Pure DAC — no guild admin bypass.
    """
    # User-specific permission
    user_level: QueuePermissionLevel | None = None
    permissions = getattr(queue, "permissions", None) or []
    for perm in permissions:
        if perm.user_id == user_id:
            user_level = perm.level
            break

    role_level = queue_role_permission_level(queue, user_id)
    effective = effective_queue_permission(user_level, role_level)
    return effective.value if effective else None


def _effective_queue_level(
    queue: Queue,
    user: User,
) -> QueuePermissionLevel | None:
    """Internal: compute effective queue permission level enum."""
    user_level: QueuePermissionLevel | None = None
    permissions = getattr(queue, "permissions", None) or []
    for perm in permissions:
        if perm.user_id == user.id:
            user_level = perm.level
            break

    role_level = queue_role_permission_level(queue, user.id)
    return effective_queue_permission(user_level, role_level)


def require_queue_access(
    queue: Queue,
    user: User,
    *,
    access: str = "read",
    require_owner: bool = False,
) -> None:
    """Raise HTTPException if user lacks required queue access.

    DAC: Access granted through explicit QueuePermission or role-based
    permission.  Effective level = MAX(user-specific, role-based).
    """
    effective = _effective_queue_level(queue, user)

    if require_owner:
        if effective != QueuePermissionLevel.owner:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=QueueMessages.OWNER_REQUIRED,
            )
        return

    if effective is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=QueueMessages.PERMISSION_REQUIRED,
        )

    if access == "write" and effective == QueuePermissionLevel.read:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=QueueMessages.WRITE_ACCESS_REQUIRED,
        )


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------

async def get_queue(
    session: AsyncSession,
    queue_id: int,
    *,
    populate_existing: bool = False,
) -> Queue | None:
    """Fetch a queue with all relationships loaded for serialization."""
    stmt = (
        select(Queue)
        .where(Queue.id == queue_id)
        .options(
            selectinload(Queue.items)
            .selectinload(QueueItem.tag_links)
            .selectinload(QueueItemTag.tag),
            selectinload(Queue.items)
            .selectinload(QueueItem.document_links)
            .selectinload(QueueItemDocument.document),
            selectinload(Queue.items)
            .selectinload(QueueItem.task_links)
            .selectinload(QueueItemTask.task),
            selectinload(Queue.items)
            .selectinload(QueueItem.user),
            selectinload(Queue.permissions),
            selectinload(Queue.role_permissions)
            .selectinload(QueueRolePermission.role),
            selectinload(Queue.initiative)
            .selectinload(Initiative.memberships),
        )
    )
    if populate_existing:
        stmt = stmt.execution_options(populate_existing=True)
    result = await session.exec(stmt)
    return result.one_or_none()


async def get_queue_item(
    session: AsyncSession,
    item_id: int,
    *,
    populate_existing: bool = False,
) -> QueueItem | None:
    """Fetch a queue item with tag/document/task/user relationships loaded."""
    stmt = (
        select(QueueItem)
        .where(QueueItem.id == item_id)
        .options(
            selectinload(QueueItem.tag_links)
            .selectinload(QueueItemTag.tag),
            selectinload(QueueItem.document_links)
            .selectinload(QueueItemDocument.document),
            selectinload(QueueItem.task_links)
            .selectinload(QueueItemTask.task),
            selectinload(QueueItem.user),
        )
    )
    if populate_existing:
        stmt = stmt.execution_options(populate_existing=True)
    result = await session.exec(stmt)
    return result.one_or_none()


# ---------------------------------------------------------------------------
# Turn management
# ---------------------------------------------------------------------------

def _visible_items_desc(queue: Queue) -> list[QueueItem]:
    """Return visible items sorted by position descending (highest first)."""
    items = getattr(queue, "items", None) or []
    return sorted(
        [item for item in items if item.is_visible],
        key=lambda item: item.position,
        reverse=True,
    )


async def advance_turn(session: AsyncSession, queue: Queue) -> Queue:
    """Advance to the next visible item by position (descending).

    Items sorted by position DESC (highest goes first, like TTRPG initiative).
    Wraps around to the first item and increments current_round.
    Skips hidden items (is_visible=False).
    """
    visible = _visible_items_desc(queue)
    if not visible:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=QueueMessages.NO_ITEMS,
        )

    # Find current item index in the sorted list
    current_idx: int | None = None
    if queue.current_item_id is not None:
        for idx, item in enumerate(visible):
            if item.id == queue.current_item_id:
                current_idx = idx
                break

    if current_idx is None or current_idx >= len(visible) - 1:
        # Not found or at end — wrap to first item and increment round
        queue.current_item_id = visible[0].id
        queue.current_round += 1
    else:
        # Move to next item
        queue.current_item_id = visible[current_idx + 1].id

    queue.updated_at = datetime.now(timezone.utc)
    session.add(queue)
    return queue


async def previous_turn(session: AsyncSession, queue: Queue) -> Queue:
    """Move to the previous visible item by position (descending).

    Reverse direction of advance_turn. Wraps around to the last item
    and decrements current_round (minimum 1).
    """
    visible = _visible_items_desc(queue)
    if not visible:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=QueueMessages.NO_ITEMS,
        )

    # Find current item index
    current_idx: int | None = None
    if queue.current_item_id is not None:
        for idx, item in enumerate(visible):
            if item.id == queue.current_item_id:
                current_idx = idx
                break

    if current_idx is None or current_idx <= 0:
        # Not found or at beginning — wrap to last item and decrement round
        queue.current_item_id = visible[-1].id
        queue.current_round = max(1, queue.current_round - 1)
    else:
        # Move to previous item
        queue.current_item_id = visible[current_idx - 1].id

    queue.updated_at = datetime.now(timezone.utc)
    session.add(queue)
    return queue


async def start_queue(session: AsyncSession, queue: Queue) -> Queue:
    """Start the queue: set is_active=True, reset to first visible item, round 1."""
    visible = _visible_items_desc(queue)
    if not visible:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=QueueMessages.NO_ITEMS,
        )

    queue.is_active = True
    queue.current_item_id = visible[0].id
    queue.current_round = 1
    queue.updated_at = datetime.now(timezone.utc)
    session.add(queue)
    return queue


async def stop_queue(session: AsyncSession, queue: Queue) -> Queue:
    """Stop the queue: set is_active=False but keep current position."""
    queue.is_active = False
    queue.updated_at = datetime.now(timezone.utc)
    session.add(queue)
    return queue


async def reset_queue(session: AsyncSession, queue: Queue) -> Queue:
    """Reset the queue: set current_round=1, current_item_id to first visible item."""
    visible = _visible_items_desc(queue)
    if not visible:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=QueueMessages.NO_ITEMS,
        )

    queue.current_round = 1
    queue.current_item_id = visible[0].id
    queue.updated_at = datetime.now(timezone.utc)
    session.add(queue)
    return queue


async def set_active_item(
    session: AsyncSession,
    queue: Queue,
    item_id: int,
) -> Queue:
    """Set the active item on a queue. Validates item belongs to the queue."""
    items = getattr(queue, "items", None) or []
    found = any(item.id == item_id for item in items)
    if not found:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=QueueMessages.ITEM_NOT_FOUND,
        )

    queue.current_item_id = item_id
    queue.updated_at = datetime.now(timezone.utc)
    session.add(queue)
    return queue


# ---------------------------------------------------------------------------
# Tag / document / task attachment helpers
# ---------------------------------------------------------------------------

async def set_queue_item_tags(
    session: AsyncSession,
    item: QueueItem,
    tag_ids: list[int],
    guild_id: int,
) -> None:
    """Replace all tags on a queue item. Validates tag_ids belong to guild."""
    if tag_ids:
        tags_stmt = select(Tag).where(
            Tag.id.in_(tag_ids),
            Tag.guild_id == guild_id,
        )
        tags_result = await session.exec(tags_stmt)
        valid_tags = tags_result.all()
        valid_tag_ids = {t.id for t in valid_tags}

        invalid_ids = set(tag_ids) - valid_tag_ids
        if invalid_ids:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=QueueMessages.INVALID_TAG_IDS,
            )

    # Remove existing tag links
    delete_stmt = sa_delete(QueueItemTag).where(
        QueueItemTag.queue_item_id == item.id,
    )
    await session.exec(delete_stmt)

    # Add new tag links
    for tag_id in tag_ids:
        link = QueueItemTag(
            queue_item_id=item.id,
            tag_id=tag_id,
        )
        session.add(link)


async def set_queue_item_documents(
    session: AsyncSession,
    item: QueueItem,
    document_ids: list[int],
    guild_id: int,
    user_id: int,
) -> None:
    """Replace all document links on a queue item.

    Validates that the referenced documents exist. The RLS layer handles
    guild/initiative access scoping, so we only do an existence check here.
    """
    if document_ids:
        docs_stmt = select(Document.id).where(Document.id.in_(document_ids))
        docs_result = await session.exec(docs_stmt)
        valid_ids = set(docs_result.all())

        missing = set(document_ids) - valid_ids
        if missing:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=QueueMessages.ITEM_NOT_FOUND,
            )

    # Remove existing document links
    delete_stmt = sa_delete(QueueItemDocument).where(
        QueueItemDocument.queue_item_id == item.id,
    )
    await session.exec(delete_stmt)

    # Add new document links
    now = datetime.now(timezone.utc)
    for doc_id in document_ids:
        link = QueueItemDocument(
            queue_item_id=item.id,
            document_id=doc_id,
            guild_id=guild_id,
            attached_by_id=user_id,
            attached_at=now,
        )
        session.add(link)


async def set_queue_item_tasks(
    session: AsyncSession,
    item: QueueItem,
    task_ids: list[int],
    guild_id: int,
    user_id: int,
) -> None:
    """Replace all task links on a queue item.

    Validates that the referenced tasks exist. The RLS layer handles
    guild/initiative access scoping, so we only do an existence check here.
    """
    if task_ids:
        tasks_stmt = select(Task.id).where(Task.id.in_(task_ids))
        tasks_result = await session.exec(tasks_stmt)
        valid_ids = set(tasks_result.all())

        missing = set(task_ids) - valid_ids
        if missing:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=QueueMessages.ITEM_NOT_FOUND,
            )

    # Remove existing task links
    delete_stmt = sa_delete(QueueItemTask).where(
        QueueItemTask.queue_item_id == item.id,
    )
    await session.exec(delete_stmt)

    # Add new task links
    now = datetime.now(timezone.utc)
    for task_id in task_ids:
        link = QueueItemTask(
            queue_item_id=item.id,
            task_id=task_id,
            guild_id=guild_id,
            attached_by_id=user_id,
            attached_at=now,
        )
        session.add(link)
