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
    """Return visible items sorted by position descending (highest first).

    Includes held items — the rotation logic in ``advance_turn`` walks the
    visible list directly so it can auto-release held items whose due slot
    has come up. Functions that want the *active* (non-held) rotation use
    :func:`_active_rotation_desc` instead.
    """
    items = getattr(queue, "items", None) or []
    return sorted(
        [item for item in items if item.is_visible],
        key=lambda item: item.position,
        reverse=True,
    )


def _active_rotation_desc(queue: Queue) -> list[QueueItem]:
    """Return rotation-eligible items (visible AND not held), position desc.

    Used by ``previous_turn``, ``start_queue``, ``reset_queue`` to land on
    items that are currently in the rotation. ``advance_turn`` and the
    hold/release helpers iterate over :func:`_visible_items_desc` instead
    because they have to consider held items for auto-release.
    """
    return [item for item in _visible_items_desc(queue) if item.held_at_round is None]


async def advance_turn(session: AsyncSession, queue: Queue) -> Queue:
    """Advance to the next rotation slot, auto-releasing any held item due.

    Walks visible items in position-desc order (with round wrap). A candidate
    that's held with ``held_at_round < new_current_round`` is auto-released
    (``held_at_round`` cleared) and becomes the current turn — so a held
    participant whose natural slot has come back around isn't silently
    skipped forever. Held items whose due round hasn't arrived are skipped.
    Mirrors the algorithm in ``advanceQueueState`` (frontend).
    """
    visible = _visible_items_desc(queue)
    if not visible:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=QueueMessages.NO_ITEMS,
        )

    # Locate the current item within the visible list (held or not).
    current_idx: int | None = None
    if queue.current_item_id is not None:
        for idx, item in enumerate(visible):
            if item.id == queue.current_item_id:
                current_idx = idx
                break

    idx = current_idx if current_idx is not None else -1
    round_ = queue.current_round
    # Cap iterations defensively; the only natural terminator is "found a
    # rotation-eligible candidate" or "every held item has a future due
    # round" (which would be a pathological state).
    for _ in range(len(visible) * 2 + 1):
        next_idx = (idx + 1) % len(visible)
        wrapped = next_idx == 0 and current_idx is not None
        if wrapped:
            round_ += 1
        candidate = visible[next_idx]
        if candidate.held_at_round is None:
            queue.current_item_id = candidate.id
            queue.current_round = round_
            queue.updated_at = datetime.now(timezone.utc)
            session.add(queue)
            return queue
        if candidate.held_at_round < round_:
            # Due: auto-release and act now.
            candidate.held_at_round = None
            session.add(candidate)
            queue.current_item_id = candidate.id
            queue.current_round = round_
            queue.updated_at = datetime.now(timezone.utc)
            session.add(queue)
            return queue
        # Held and not yet due — skip past it.
        idx = next_idx
        current_idx = next_idx  # subsequent wraps should bump round

    # Every item in the rotation is held and not yet due. Clear current and
    # leave the round where we landed; user can release manually.
    queue.current_item_id = None
    queue.current_round = round_
    queue.updated_at = datetime.now(timezone.utc)
    session.add(queue)
    return queue


async def previous_turn(session: AsyncSession, queue: Queue) -> Queue:
    """Move to the previous rotation-eligible item by position (descending).

    Held items are skipped without auto-release — auto-release is a forward-
    time effect of :func:`advance_turn` only. Wraps to the last and
    decrements ``current_round`` (minimum 1).
    """
    rotation = _active_rotation_desc(queue)
    if not rotation:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=QueueMessages.NO_ITEMS,
        )

    current_idx: int | None = None
    if queue.current_item_id is not None:
        for idx, item in enumerate(rotation):
            if item.id == queue.current_item_id:
                current_idx = idx
                break

    if current_idx is None or current_idx <= 0:
        queue.current_item_id = rotation[-1].id
        queue.current_round = max(1, queue.current_round - 1)
    else:
        queue.current_item_id = rotation[current_idx - 1].id

    queue.updated_at = datetime.now(timezone.utc)
    session.add(queue)
    return queue


async def start_queue(session: AsyncSession, queue: Queue) -> Queue:
    """Start the queue: set is_active=True, reset to first rotation item, round 1."""
    rotation = _active_rotation_desc(queue)
    if not rotation:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=QueueMessages.NO_ITEMS,
        )

    queue.is_active = True
    queue.current_item_id = rotation[0].id
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
    """Reset the queue: round=1, current = first rotation item. Held state preserved."""
    rotation = _active_rotation_desc(queue)
    if not rotation:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=QueueMessages.NO_ITEMS,
        )

    queue.current_round = 1
    queue.current_item_id = rotation[0].id
    queue.updated_at = datetime.now(timezone.utc)
    session.add(queue)
    return queue


async def set_active_item(
    session: AsyncSession,
    queue: Queue,
    item_id: int,
) -> Queue:
    """Set the active item on a queue. Validates item belongs to the queue.

    If the target is currently held, ``held_at_round`` is cleared as part of
    the same operation — the invariant ``current ∉ held set`` should survive
    any direct-set path so the rotation doesn't enter a state where its
    current pointer references a held item.
    """
    items = getattr(queue, "items", None) or []
    target: QueueItem | None = next((item for item in items if item.id == item_id), None)
    if target is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=QueueMessages.ITEM_NOT_FOUND,
        )

    if target.held_at_round is not None:
        target.held_at_round = None
        session.add(target)
    queue.current_item_id = item_id
    queue.updated_at = datetime.now(timezone.utc)
    session.add(queue)
    return queue


async def hold_current(session: AsyncSession, queue: Queue) -> Queue:
    """Hold the current turn — record the round and advance to the next item.

    The held item leaves the rotation immediately. ``current_item_id``
    advances to the next rotation slot, skipping any other held items whose
    due round hasn't arrived. If holding empties the rotation,
    ``current_item_id`` is cleared and the round is unchanged.
    """
    if queue.current_item_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=QueueMessages.NO_CURRENT_ITEM,
        )
    items = getattr(queue, "items", None) or []
    current = next((item for item in items if item.id == queue.current_item_id), None)
    if current is None:
        # current_item_id pointing at a deleted/missing row; treat as "no current"
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=QueueMessages.NO_CURRENT_ITEM,
        )

    # Record the hold *before* advancing so the rotation skips this item.
    current.held_at_round = queue.current_round
    session.add(current)

    # Find the next rotation-eligible slot in position-desc order, with wrap.
    visible = _visible_items_desc(queue)
    rotation = [item for item in visible if item.held_at_round is None]
    if not rotation:
        queue.current_item_id = None
        queue.updated_at = datetime.now(timezone.utc)
        session.add(queue)
        return queue

    # Locate where we *were* in the full visible list; advance from there to
    # the next non-held slot, wrapping and bumping round if needed.
    current_idx = next(
        (idx for idx, item in enumerate(visible) if item.id == current.id),
        -1,
    )
    round_ = queue.current_round
    for step in range(1, len(visible) + 1):
        next_idx = (current_idx + step) % len(visible)
        if next_idx <= current_idx:
            round_ = queue.current_round + 1
        candidate = visible[next_idx]
        if candidate.held_at_round is None:
            queue.current_item_id = candidate.id
            queue.current_round = round_
            break

    queue.updated_at = datetime.now(timezone.utc)
    session.add(queue)
    return queue


async def release_held(
    session: AsyncSession,
    queue: Queue,
    item_id: int,
    *,
    reposition: bool = False,
) -> Queue:
    """Manually release a held item back into the rotation.

    Clears ``held_at_round`` on the target so it rejoins the active rotation.
    ``current_item_id``, ``current_round``, and ``is_active`` are deliberately
    untouched — releasing a hold shouldn't rewind the rotation pointer onto
    items that already took their turn this round.

    When ``reposition`` is True (PF2e Delay semantics), the target acts now
    — it becomes the current turn, and its ``position`` is rewritten to land
    just above the previous current item in the position-desc rotation
    (midpoint between the previous current and the next-higher active item,
    or ``current.position + 1`` if current was the top of the rotation). The
    new initiative slot persists for the rest of the encounter, exactly like
    a PF2e Delay re-entry. Default ``False`` keeps the released item at its
    original position so it acts at its natural slot the next time the
    rotation reaches it, without disrupting the current pointer.
    """
    items = getattr(queue, "items", None) or []
    target = next((item for item in items if item.id == item_id), None)
    if target is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=QueueMessages.ITEM_NOT_FOUND,
        )
    if target.held_at_round is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=QueueMessages.ITEM_NOT_HELD,
        )

    target.held_at_round = None

    if reposition and queue.current_item_id is not None and queue.current_item_id != target.id:
        current = next((x for x in items if x.id == queue.current_item_id), None)
        if current is not None:
            # Next active item whose position is strictly above current's
            # (held items and the target itself excluded).
            actives_above = sorted(
                (
                    x
                    for x in items
                    if x.is_visible
                    and x.held_at_round is None
                    and x.id != target.id
                    and x.id != current.id
                    and x.position > current.position
                ),
                key=lambda x: x.position,
            )
            if actives_above:
                target.position = (current.position + actives_above[0].position) / 2
            else:
                # Current was already the top — drop the released item just
                # above it. +1.0 is arbitrary but safely over any other
                # active position relative to current.
                target.position = current.position + 1.0
            # They're acting *now*, before the previous current's turn — take
            # over the current pointer so the rotation reflects that.
            queue.current_item_id = target.id

    session.add(target)
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
