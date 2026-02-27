"""Queue endpoints — CRUD, turn management, item management, and DAC permissions.

Initiative-scoped queues for turn/priority tracking (e.g., TTRPG initiative order).
Follows the document endpoint patterns for RLS, DAC, and initiative permission checks.
"""

from datetime import datetime, timezone
from typing import Annotated, List, Optional

import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect, status
from sqlalchemy import delete as sa_delete, func
from sqlalchemy.orm import selectinload
from sqlmodel import select

from app.api.deps import (
    RLSSessionDep,
    get_current_active_user,
    get_guild_membership,
    GuildContext,
)
from app.core.config import settings
from app.db.session import AsyncSessionLocal, reapply_rls_context, set_rls_context
from app.models.queue import (
    Queue,
    QueueItem,
    QueuePermission,
    QueuePermissionLevel,
    QueueRolePermission,
)
from app.models.guild import GuildMembership
from app.models.initiative import Initiative, InitiativeMember, InitiativeRoleModel, PermissionKey
from app.models.user import User
from app.schemas.token import TokenPayload
from app.core.messages import QueueMessages, InitiativeMessages
from app.schemas.queue import (
    QueueCreate,
    QueueUpdate,
    QueueRead,
    QueueListResponse,
    QueueItemCreate,
    QueueItemUpdate,
    QueueItemRead,
    QueueItemReorderRequest,
    QueuePermissionCreate,
    QueuePermissionRead,
    QueueRolePermissionCreate,
    QueueRolePermissionRead,
    serialize_queue,
    serialize_queue_summary,
    serialize_queue_item,
)
from app.services import queues as queues_service
from app.services import rls as rls_service
from app.services import user_tokens
from app.services.queue_realtime import queue_manager

import jwt

router = APIRouter()
logger = logging.getLogger(__name__)

GuildContextDep = Annotated[GuildContext, Depends(get_guild_membership)]


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


async def _get_initiative_for_queue(
    session: RLSSessionDep,
    initiative_id: int,
) -> Initiative:
    """Fetch initiative or 404."""
    stmt = (
        select(Initiative)
        .where(Initiative.id == initiative_id)
        .options(
            selectinload(Initiative.memberships),
            selectinload(Initiative.roles),
        )
    )
    result = await session.exec(stmt)
    initiative = result.one_or_none()
    if not initiative:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=InitiativeMessages.NOT_FOUND,
        )
    return initiative


async def _check_initiative_permission(
    session: RLSSessionDep,
    initiative: Initiative,
    user: User,
    guild_context: GuildContext,
    permission_key: PermissionKey,
) -> None:
    """Check initiative role permission, raise 403 if denied."""
    # Guild admins bypass initiative permissions
    if rls_service.is_guild_admin(guild_context.role):
        return
    has_perm = await rls_service.check_initiative_permission(
        session,
        initiative_id=initiative.id,
        user=user,
        permission_key=permission_key,
    )
    if not has_perm:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=QueueMessages.CREATE_PERMISSION_REQUIRED,
        )


async def _get_queue_with_access(
    session: RLSSessionDep,
    queue_id: int,
    user: User,
    guild_context: GuildContext,
    *,
    access: str = "read",
) -> Queue:
    """Fetch queue with relationships and check DAC access."""
    queue = await queues_service.get_queue(session, queue_id)
    if not queue:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=QueueMessages.NOT_FOUND,
        )
    # Guild admins bypass DAC
    if not rls_service.is_guild_admin(guild_context.role):
        queues_service.require_queue_access(queue, user, access=access)
    return queue


async def _get_item_for_queue(
    session: RLSSessionDep,
    queue_id: int,
    item_id: int,
) -> QueueItem:
    """Fetch a queue item and validate it belongs to the queue."""
    item = await queues_service.get_queue_item(session, item_id)
    if not item or item.queue_id != queue_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=QueueMessages.ITEM_NOT_FOUND,
        )
    return item


def _compute_my_permission(queue: Queue, user: User, guild_context: GuildContext) -> str | None:
    """Compute effective permission level for the current user on a queue."""
    if rls_service.is_guild_admin(guild_context.role):
        return QueuePermissionLevel.owner.value
    return queues_service.compute_queue_permission(queue, user.id)


async def _refetch_queue(
    session: RLSSessionDep,
    queue_id: int,
) -> Queue:
    """Re-fetch a queue after commit + reapply_rls_context for serialization.

    Uses populate_existing=True so selectinload returns fresh relationship data
    (needed because expire_on_commit=False keeps stale collections in identity map).
    """
    queue = await queues_service.get_queue(session, queue_id, populate_existing=True)
    if not queue:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=QueueMessages.NOT_FOUND,
        )
    return queue


# ---------------------------------------------------------------------------
# Queue CRUD
# ---------------------------------------------------------------------------


@router.get("/", response_model=QueueListResponse)
async def list_queues(
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
    initiative_id: Optional[int] = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> QueueListResponse:
    """List queues visible to the current user.

    DAC: Queues with explicit QueuePermission or role-based permission.
    Guild admins see all queues.
    """
    conditions = [Queue.guild_id == guild_context.guild_id]

    if initiative_id is not None:
        conditions.append(Queue.initiative_id == initiative_id)

    # DAC filtering: non-admins only see queues they have permission for
    if not rls_service.is_guild_admin(guild_context.role):
        visible_subq = queues_service.visible_queue_ids_subquery(current_user.id)
        conditions.append(Queue.id.in_(visible_subq))

    # Count query
    count_subq = select(Queue.id).where(*conditions).subquery()
    count_stmt = select(func.count()).select_from(count_subq)
    total_count = (await session.exec(count_stmt)).one()

    # Data query with eager loading for serialization
    stmt = (
        select(Queue)
        .where(*conditions)
        .options(
            selectinload(Queue.items),
            selectinload(Queue.permissions),
            selectinload(Queue.role_permissions),
            selectinload(Queue.initiative).selectinload(Initiative.memberships),
        )
        .order_by(Queue.updated_at.desc(), Queue.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    result = await session.exec(stmt)
    queues = result.unique().all()

    items = [
        serialize_queue_summary(
            q,
            my_permission_level=_compute_my_permission(q, current_user, guild_context),
        )
        for q in queues
    ]

    has_next = page * page_size < total_count
    return QueueListResponse(
        items=items,
        total_count=total_count,
        page=page,
        page_size=page_size,
        has_next=has_next,
    )


@router.get("/{queue_id}", response_model=QueueRead)
async def read_queue(
    queue_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> QueueRead:
    """Get a queue with all items, permissions, and current state."""
    queue = await _get_queue_with_access(session, queue_id, current_user, guild_context, access="read")
    return serialize_queue(
        queue,
        my_permission_level=_compute_my_permission(queue, current_user, guild_context),
    )


@router.post("/", response_model=QueueRead, status_code=status.HTTP_201_CREATED)
async def create_queue(
    queue_in: QueueCreate,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> QueueRead:
    """Create a new queue in an initiative.

    Requires create_queues permission on the initiative (or guild admin).
    The creator automatically gets owner-level permission.
    """
    initiative = await _get_initiative_for_queue(session, queue_in.initiative_id)
    if not initiative.queues_enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=QueueMessages.FEATURE_DISABLED,
        )
    await _check_initiative_permission(
        session,
        initiative,
        current_user,
        guild_context,
        PermissionKey.create_queues,
    )

    queue = Queue(
        guild_id=guild_context.guild_id,
        initiative_id=initiative.id,
        created_by_id=current_user.id,
        name=queue_in.name.strip(),
        description=queue_in.description,
    )
    session.add(queue)
    await session.flush()

    # Owner permission for the creator
    owner_perm = QueuePermission(
        queue_id=queue.id,
        user_id=current_user.id,
        guild_id=guild_context.guild_id,
        level=QueuePermissionLevel.owner,
    )
    session.add(owner_perm)

    # Process optional role permissions
    if queue_in.role_permissions:
        role_ids = {rp.initiative_role_id for rp in queue_in.role_permissions if rp.level != QueuePermissionLevel.owner}
        valid_role_ids: set[int] = set()
        if role_ids:
            result = await session.exec(
                select(InitiativeRoleModel.id).where(
                    InitiativeRoleModel.id.in_(role_ids),
                    InitiativeRoleModel.initiative_id == initiative.id,
                )
            )
            valid_role_ids = set(result.all())
        for rp in queue_in.role_permissions:
            if rp.initiative_role_id not in valid_role_ids or rp.level == QueuePermissionLevel.owner:
                continue
            session.add(QueueRolePermission(
                queue_id=queue.id,
                initiative_role_id=rp.initiative_role_id,
                guild_id=guild_context.guild_id,
                level=rp.level,
            ))

    # Process optional user permissions
    if queue_in.user_permissions:
        requested = {up.user_id for up in queue_in.user_permissions if up.user_id != current_user.id}
        valid_ids: set[int] = set()
        if requested:
            result = await session.exec(
                select(InitiativeMember.user_id).where(
                    InitiativeMember.initiative_id == initiative.id,
                    InitiativeMember.user_id.in_(requested),
                )
            )
            valid_ids = set(result.all())
        for up in queue_in.user_permissions:
            if up.user_id in valid_ids and up.level != QueuePermissionLevel.owner:
                session.add(QueuePermission(
                    queue_id=queue.id,
                    user_id=up.user_id,
                    guild_id=guild_context.guild_id,
                    level=up.level,
                ))

    await session.commit()
    await reapply_rls_context(session)

    hydrated = await _refetch_queue(session, queue.id)
    return serialize_queue(
        hydrated,
        my_permission_level=_compute_my_permission(hydrated, current_user, guild_context),
    )


@router.patch("/{queue_id}", response_model=QueueRead)
async def update_queue(
    queue_id: int,
    queue_in: QueueUpdate,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> QueueRead:
    """Update queue name/description. Requires write access."""
    queue = await _get_queue_with_access(session, queue_id, current_user, guild_context, access="write")
    updated = False
    update_data = queue_in.model_dump(exclude_unset=True)

    if "name" in update_data and update_data["name"] is not None:
        queue.name = update_data["name"].strip()
        updated = True
    if "description" in update_data:
        queue.description = update_data["description"]
        updated = True

    if updated:
        queue.updated_at = datetime.now(timezone.utc)
        session.add(queue)
        await session.commit()
        await reapply_rls_context(session)

    hydrated = await _refetch_queue(session, queue.id)
    result = serialize_queue(
        hydrated,
        my_permission_level=_compute_my_permission(hydrated, current_user, guild_context),
    )
    if updated:
        await queue_manager.broadcast(queue_id, "queue_updated", result.model_dump(mode="json"))
    return result


@router.delete("/{queue_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_queue(
    queue_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> None:
    """Delete a queue. Requires owner permission or guild admin."""
    queue = await _get_queue_with_access(session, queue_id, current_user, guild_context, access="read")
    # Require owner or guild admin
    if not rls_service.is_guild_admin(guild_context.role):
        queues_service.require_queue_access(queue, current_user, require_owner=True)
    await session.delete(queue)
    await session.commit()
    await queue_manager.broadcast(queue_id, "queue_deleted", {"id": queue_id})


# ---------------------------------------------------------------------------
# Queue Items
# ---------------------------------------------------------------------------


@router.post("/{queue_id}/items", response_model=QueueItemRead, status_code=status.HTTP_201_CREATED)
async def add_queue_item(
    queue_id: int,
    item_in: QueueItemCreate,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> QueueItemRead:
    """Add an item to a queue. Requires write access."""
    queue = await _get_queue_with_access(session, queue_id, current_user, guild_context, access="write")

    item = QueueItem(
        guild_id=queue.guild_id,
        queue_id=queue.id,
        label=item_in.label,
        position=item_in.position,
        user_id=item_in.user_id,
        color=item_in.color,
        notes=item_in.notes,
        is_visible=item_in.is_visible,
    )
    session.add(item)
    await session.flush()

    # Set tags if provided
    if item_in.tag_ids:
        await queues_service.set_queue_item_tags(
            session, item, item_in.tag_ids, queue.guild_id,
        )

    # Set document links if provided
    if item_in.document_ids:
        await queues_service.set_queue_item_documents(
            session, item, item_in.document_ids, queue.guild_id, current_user.id,
        )

    # Set task links if provided
    if item_in.task_ids:
        await queues_service.set_queue_item_tasks(
            session, item, item_in.task_ids, queue.guild_id, current_user.id,
        )

    await session.commit()
    await reapply_rls_context(session)

    hydrated_item = await queues_service.get_queue_item(session, item.id, populate_existing=True)
    if not hydrated_item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=QueueMessages.ITEM_NOT_FOUND,
        )
    result = serialize_queue_item(hydrated_item)
    await queue_manager.broadcast(queue_id, "item_added", result.model_dump(mode="json"))
    return result


@router.patch("/{queue_id}/items/{item_id}", response_model=QueueItemRead)
async def update_queue_item(
    queue_id: int,
    item_id: int,
    item_in: QueueItemUpdate,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> QueueItemRead:
    """Update a queue item. Requires write access on the queue."""
    await _get_queue_with_access(session, queue_id, current_user, guild_context, access="write")
    item = await _get_item_for_queue(session, queue_id, item_id)

    updated = False
    update_data = item_in.model_dump(exclude_unset=True)

    for field in ("label", "position", "user_id", "color", "notes", "is_visible"):
        if field in update_data:
            setattr(item, field, update_data[field])
            updated = True

    if updated:
        session.add(item)
        await session.commit()
        await reapply_rls_context(session)

    hydrated_item = await queues_service.get_queue_item(session, item.id, populate_existing=True)
    if not hydrated_item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=QueueMessages.ITEM_NOT_FOUND,
        )
    result = serialize_queue_item(hydrated_item)
    await queue_manager.broadcast(queue_id, "item_updated", result.model_dump(mode="json"))
    return result


@router.delete("/{queue_id}/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_queue_item(
    queue_id: int,
    item_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> None:
    """Remove an item from a queue. Requires write access."""
    queue = await _get_queue_with_access(session, queue_id, current_user, guild_context, access="write")
    item = await _get_item_for_queue(session, queue_id, item_id)

    # If this item is the current active item, clear it
    if queue.current_item_id == item.id:
        queue.current_item_id = None
        session.add(queue)

    await session.delete(item)
    await session.commit()
    await queue_manager.broadcast(queue_id, "item_removed", {"id": item_id})


@router.put("/{queue_id}/items/reorder", response_model=QueueRead)
async def reorder_queue_items(
    queue_id: int,
    reorder_in: QueueItemReorderRequest,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> QueueRead:
    """Bulk reorder queue items. Requires write access."""
    queue = await _get_queue_with_access(session, queue_id, current_user, guild_context, access="write")

    # Build a map of existing items for validation
    existing_items = {item.id: item for item in (queue.items or [])}

    for reorder_item in reorder_in.items:
        item = existing_items.get(reorder_item.id)
        if item is not None:
            item.position = reorder_item.position
            session.add(item)

    queue.updated_at = datetime.now(timezone.utc)
    session.add(queue)
    await session.commit()
    await reapply_rls_context(session)

    hydrated = await _refetch_queue(session, queue.id)
    result = serialize_queue(
        hydrated,
        my_permission_level=_compute_my_permission(hydrated, current_user, guild_context),
    )
    await queue_manager.broadcast(queue_id, "items_reordered", result.model_dump(mode="json"))
    return result


# ---------------------------------------------------------------------------
# Turn Management
# ---------------------------------------------------------------------------


@router.post("/{queue_id}/start", response_model=QueueRead)
async def start_queue(
    queue_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> QueueRead:
    """Start the queue: set active, reset to first item, round 1."""
    queue = await _get_queue_with_access(session, queue_id, current_user, guild_context, access="write")
    await queues_service.start_queue(session, queue)
    await session.commit()
    await reapply_rls_context(session)

    hydrated = await _refetch_queue(session, queue.id)
    result = serialize_queue(
        hydrated,
        my_permission_level=_compute_my_permission(hydrated, current_user, guild_context),
    )
    await queue_manager.broadcast(queue_id, "queue_started", result.model_dump(mode="json"))
    return result


@router.post("/{queue_id}/stop", response_model=QueueRead)
async def stop_queue(
    queue_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> QueueRead:
    """Stop the queue: set inactive but keep current position."""
    queue = await _get_queue_with_access(session, queue_id, current_user, guild_context, access="write")
    await queues_service.stop_queue(session, queue)
    await session.commit()
    await reapply_rls_context(session)

    hydrated = await _refetch_queue(session, queue.id)
    result = serialize_queue(
        hydrated,
        my_permission_level=_compute_my_permission(hydrated, current_user, guild_context),
    )
    await queue_manager.broadcast(queue_id, "queue_stopped", result.model_dump(mode="json"))
    return result


@router.post("/{queue_id}/next", response_model=QueueRead)
async def advance_turn(
    queue_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> QueueRead:
    """Advance to the next visible item. Wraps around and increments round."""
    queue = await _get_queue_with_access(session, queue_id, current_user, guild_context, access="write")
    await queues_service.advance_turn(session, queue)
    await session.commit()
    await reapply_rls_context(session)

    hydrated = await _refetch_queue(session, queue.id)
    result = serialize_queue(
        hydrated,
        my_permission_level=_compute_my_permission(hydrated, current_user, guild_context),
    )
    await queue_manager.broadcast(queue_id, "turn_advance", result.model_dump(mode="json"))
    return result


@router.post("/{queue_id}/previous", response_model=QueueRead)
async def previous_turn(
    queue_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> QueueRead:
    """Move to the previous visible item. Wraps around and decrements round."""
    queue = await _get_queue_with_access(session, queue_id, current_user, guild_context, access="write")
    await queues_service.previous_turn(session, queue)
    await session.commit()
    await reapply_rls_context(session)

    hydrated = await _refetch_queue(session, queue.id)
    result = serialize_queue(
        hydrated,
        my_permission_level=_compute_my_permission(hydrated, current_user, guild_context),
    )
    await queue_manager.broadcast(queue_id, "turn_previous", result.model_dump(mode="json"))
    return result


@router.post("/{queue_id}/set-active/{item_id}", response_model=QueueRead)
async def set_active_item(
    queue_id: int,
    item_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> QueueRead:
    """Jump to a specific item in the queue."""
    queue = await _get_queue_with_access(session, queue_id, current_user, guild_context, access="write")
    await queues_service.set_active_item(session, queue, item_id)
    await session.commit()
    await reapply_rls_context(session)

    hydrated = await _refetch_queue(session, queue.id)
    result = serialize_queue(
        hydrated,
        my_permission_level=_compute_my_permission(hydrated, current_user, guild_context),
    )
    await queue_manager.broadcast(queue_id, "turn_set_active", result.model_dump(mode="json"))
    return result


@router.post("/{queue_id}/reset", response_model=QueueRead)
async def reset_queue(
    queue_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> QueueRead:
    """Reset the queue to round 1, first visible item."""
    queue = await _get_queue_with_access(session, queue_id, current_user, guild_context, access="write")
    await queues_service.reset_queue(session, queue)
    await session.commit()
    await reapply_rls_context(session)

    hydrated = await _refetch_queue(session, queue.id)
    result = serialize_queue(
        hydrated,
        my_permission_level=_compute_my_permission(hydrated, current_user, guild_context),
    )
    await queue_manager.broadcast(queue_id, "queue_reset", result.model_dump(mode="json"))
    return result


# ---------------------------------------------------------------------------
# Item Tags
# ---------------------------------------------------------------------------


@router.put("/{queue_id}/items/{item_id}/tags", response_model=QueueItemRead)
async def set_queue_item_tags(
    queue_id: int,
    item_id: int,
    tag_ids: List[int],
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> QueueItemRead:
    """Set tags on a queue item. Replaces all existing tags."""
    queue = await _get_queue_with_access(session, queue_id, current_user, guild_context, access="write")
    item = await _get_item_for_queue(session, queue_id, item_id)

    await queues_service.set_queue_item_tags(session, item, tag_ids, queue.guild_id)
    await session.commit()
    await reapply_rls_context(session)

    hydrated_item = await queues_service.get_queue_item(session, item.id, populate_existing=True)
    if not hydrated_item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=QueueMessages.ITEM_NOT_FOUND,
        )
    result = serialize_queue_item(hydrated_item)
    await queue_manager.broadcast(queue_id, "tags_changed", result.model_dump(mode="json"))
    return result


# ---------------------------------------------------------------------------
# Item Attachments (documents, tasks)
# ---------------------------------------------------------------------------


@router.put("/{queue_id}/items/{item_id}/documents", response_model=QueueItemRead)
async def set_queue_item_documents(
    queue_id: int,
    item_id: int,
    document_ids: List[int],
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> QueueItemRead:
    """Set document links on a queue item. Replaces all existing links."""
    queue = await _get_queue_with_access(session, queue_id, current_user, guild_context, access="write")
    item = await _get_item_for_queue(session, queue_id, item_id)

    await queues_service.set_queue_item_documents(
        session, item, document_ids, queue.guild_id, current_user.id,
    )
    await session.commit()
    await reapply_rls_context(session)

    hydrated_item = await queues_service.get_queue_item(session, item.id, populate_existing=True)
    if not hydrated_item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=QueueMessages.ITEM_NOT_FOUND,
        )
    result = serialize_queue_item(hydrated_item)
    await queue_manager.broadcast(queue_id, "documents_changed", result.model_dump(mode="json"))
    return result


@router.put("/{queue_id}/items/{item_id}/tasks", response_model=QueueItemRead)
async def set_queue_item_tasks(
    queue_id: int,
    item_id: int,
    task_ids: List[int],
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> QueueItemRead:
    """Set task links on a queue item. Replaces all existing links."""
    queue = await _get_queue_with_access(session, queue_id, current_user, guild_context, access="write")
    item = await _get_item_for_queue(session, queue_id, item_id)

    await queues_service.set_queue_item_tasks(
        session, item, task_ids, queue.guild_id, current_user.id,
    )
    await session.commit()
    await reapply_rls_context(session)

    hydrated_item = await queues_service.get_queue_item(session, item.id, populate_existing=True)
    if not hydrated_item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=QueueMessages.ITEM_NOT_FOUND,
        )
    result = serialize_queue_item(hydrated_item)
    await queue_manager.broadcast(queue_id, "tasks_changed", result.model_dump(mode="json"))
    return result


# ---------------------------------------------------------------------------
# Permissions (DAC)
# ---------------------------------------------------------------------------


@router.get("/{queue_id}/permissions")
async def list_queue_permissions(
    queue_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> dict:
    """List user and role permissions on a queue. Requires read access."""
    queue = await _get_queue_with_access(session, queue_id, current_user, guild_context, access="read")

    permissions = [
        QueuePermissionRead(
            user_id=p.user_id,
            level=p.level,
            created_at=p.created_at,
        )
        for p in (queue.permissions or [])
    ]

    role_permissions = []
    for rp in (queue.role_permissions or []):
        role = getattr(rp, "role", None)
        role_permissions.append(QueueRolePermissionRead(
            initiative_role_id=rp.initiative_role_id,
            role_name=getattr(role, "name", "") if role else "",
            role_display_name=getattr(role, "display_name", "") if role else "",
            level=rp.level,
            created_at=rp.created_at,
        ))

    return {
        "permissions": permissions,
        "role_permissions": role_permissions,
    }


@router.put("/{queue_id}/permissions", response_model=List[QueuePermissionRead])
async def set_queue_permissions(
    queue_id: int,
    permissions_in: List[QueuePermissionCreate],
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> List[QueuePermissionRead]:
    """Set user permissions on a queue. Requires owner or guild admin.

    Replaces all non-owner permissions. The owner's permission cannot be changed.
    """
    queue = await _get_queue_with_access(session, queue_id, current_user, guild_context, access="read")
    if not rls_service.is_guild_admin(guild_context.role):
        queues_service.require_queue_access(queue, current_user, require_owner=True)

    # Find the owner's user_id
    owner_user_id: int | None = None
    for p in (queue.permissions or []):
        if p.level == QueuePermissionLevel.owner:
            owner_user_id = p.user_id
            break

    # Delete all non-owner permissions
    if owner_user_id is not None:
        delete_stmt = sa_delete(QueuePermission).where(
            QueuePermission.queue_id == queue.id,
            QueuePermission.user_id != owner_user_id,
        )
    else:
        delete_stmt = sa_delete(QueuePermission).where(
            QueuePermission.queue_id == queue.id,
            QueuePermission.level != QueuePermissionLevel.owner,
        )
    await session.exec(delete_stmt)

    # Add new permissions (skip owner-level and skip the current owner)
    for perm_in in permissions_in:
        if perm_in.user_id == owner_user_id:
            continue
        if perm_in.level == QueuePermissionLevel.owner:
            continue
        session.add(QueuePermission(
            queue_id=queue.id,
            user_id=perm_in.user_id,
            guild_id=queue.guild_id,
            level=perm_in.level,
        ))

    await session.commit()
    await reapply_rls_context(session)

    hydrated = await _refetch_queue(session, queue.id)
    perms_result = [
        QueuePermissionRead(
            user_id=p.user_id,
            level=p.level,
            created_at=p.created_at,
        )
        for p in (hydrated.permissions or [])
    ]
    await queue_manager.broadcast(
        queue_id, "permissions_changed",
        {"permissions": [p.model_dump(mode="json") for p in perms_result]},
    )
    return perms_result


@router.put("/{queue_id}/role-permissions", response_model=List[QueueRolePermissionRead])
async def set_queue_role_permissions(
    queue_id: int,
    role_permissions_in: List[QueueRolePermissionCreate],
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> List[QueueRolePermissionRead]:
    """Set role permissions on a queue. Requires owner or guild admin.

    Replaces all existing role permissions.
    """
    queue = await _get_queue_with_access(session, queue_id, current_user, guild_context, access="read")
    if not rls_service.is_guild_admin(guild_context.role):
        queues_service.require_queue_access(queue, current_user, require_owner=True)

    # Delete all existing role permissions
    delete_stmt = sa_delete(QueueRolePermission).where(
        QueueRolePermission.queue_id == queue.id,
    )
    await session.exec(delete_stmt)

    # Add new role permissions (skip owner-level)
    for rp_in in role_permissions_in:
        if rp_in.level == QueuePermissionLevel.owner:
            continue
        session.add(QueueRolePermission(
            queue_id=queue.id,
            initiative_role_id=rp_in.initiative_role_id,
            guild_id=queue.guild_id,
            level=rp_in.level,
        ))

    await session.commit()
    await reapply_rls_context(session)

    hydrated = await _refetch_queue(session, queue.id)
    role_perms_result: List[QueueRolePermissionRead] = []
    for rp in (hydrated.role_permissions or []):
        role = getattr(rp, "role", None)
        role_perms_result.append(QueueRolePermissionRead(
            initiative_role_id=rp.initiative_role_id,
            role_name=getattr(role, "name", "") if role else "",
            role_display_name=getattr(role, "display_name", "") if role else "",
            level=rp.level,
            created_at=rp.created_at,
        ))
    await queue_manager.broadcast(
        queue_id, "permissions_changed",
        {"role_permissions": [rp.model_dump(mode="json") for rp in role_perms_result]},
    )
    return role_perms_result


# ---------------------------------------------------------------------------
# WebSocket — Real-time queue updates
# ---------------------------------------------------------------------------


async def _ws_authenticate(token: str, session) -> Optional[User]:
    """Validate JWT or device token and return the user."""
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        token_data = TokenPayload(**payload)
        if token_data.sub:
            stmt = select(User).where(User.id == int(token_data.sub))
            result = await session.exec(stmt)
            user = result.one_or_none()
            if user and user.is_active:
                return user
    except jwt.PyJWTError:
        pass

    device_token = await user_tokens.get_device_token(session, token=token)
    if device_token:
        stmt = select(User).where(User.id == device_token.user_id)
        result = await session.exec(stmt)
        user = result.one_or_none()
        if user and user.is_active:
            return user
    return None


@router.websocket("/{queue_id}/ws")
async def websocket_queue(
    websocket: WebSocket,
    queue_id: int,
) -> None:
    """WebSocket for real-time queue updates (server-to-client broadcast).

    Protocol:
    1. Client connects and sends JSON: {"token": "...", "guild_id": 123}
    2. Server validates auth and initiative membership
    3. Server broadcasts JSON events as queue state changes
    4. Client keeps connection alive; no client-to-server data expected

    Event types: turn_advance, turn_previous, item_added, item_removed,
    item_updated, tags_changed, queue_started, queue_stopped, queue_reset,
    items_reordered, queue_updated, queue_deleted, documents_changed,
    tasks_changed, permissions_changed
    """
    await websocket.accept()

    # Wait for auth message
    try:
        raw = await websocket.receive_text()
        auth_payload = json.loads(raw)
        token = auth_payload.get("token")
        guild_id = auth_payload.get("guild_id")
        if not token:
            token = websocket.cookies.get(settings.COOKIE_NAME)
        if not token or guild_id is None:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return
        guild_id = int(guild_id)
    except (json.JSONDecodeError, ValueError, WebSocketDisconnect):
        try:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        except Exception:
            pass
        return

    # Authenticate and check access using a short-lived session
    async with AsyncSessionLocal() as session:
        user = await _ws_authenticate(token, session)
        if not user:
            logger.warning(f"Queue WS: auth failed for queue {queue_id}")
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

        await set_rls_context(session, user_id=user.id, guild_id=guild_id)

        # Verify guild membership
        stmt = select(GuildMembership).where(
            GuildMembership.guild_id == guild_id,
            GuildMembership.user_id == user.id,
        )
        result = await session.exec(stmt)
        membership = result.one_or_none()
        if not membership:
            logger.warning(f"Queue WS: user {user.id} not in guild {guild_id}")
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

        # Fetch queue and check DAC
        queue = await queues_service.get_queue(session, queue_id)
        if not queue or queue.guild_id != guild_id:
            logger.warning(f"Queue WS: queue {queue_id} not found in guild {guild_id}")
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

        is_admin = rls_service.is_guild_admin(membership.role)
        if not is_admin:
            level = queues_service.compute_queue_permission(queue, user.id)
            if level is None:
                logger.warning(f"Queue WS: user {user.id} has no access to queue {queue_id}")
                await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
                return

    # Join the room
    await queue_manager.connect(queue_id, websocket)
    logger.info(f"Queue WS: user {user.id} joined queue {queue_id}")

    try:
        # Keep the connection alive — listen for pings/disconnects
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await queue_manager.disconnect(queue_id, websocket)
        logger.info(f"Queue WS: user {user.id} left queue {queue_id}")
