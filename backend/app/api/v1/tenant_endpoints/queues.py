"""Queue endpoints — CRUD, turn management, item management, and DAC permissions.

Initiative-scoped queues for turn/priority tracking (e.g., TTRPG initiative order).
Follows the document endpoint patterns for RLS, DAC, and initiative permission checks.
"""

from datetime import datetime, timezone
from typing import Annotated, Optional

import logging

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    WebSocket,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import routed_guild_id
from app.core.relationships import Related, RelationshipType
from app.core.search import SearchEntityType
from app.models.tenant.document import Document
from app.models.tenant.task import Task
from app.services.tenant import relationships
from app.api.actor_route import ActorRoute
from app.api.deps import (
    ActorContext,
    ActorSessionDep,
    ActorUserDep,
    IncludeDeletedDep,
    RLSSessionDep,
    app_scope,
    get_current_active_user,
    get_guild_membership,
    GuildContext,
)
from app.models.tenant.queue import (
    Queue,
    QueueItem,
)
from app.models.platform.user import User
from app.core.messages import QueueMessages
from app.schemas.tenant.queue import (
    QueueCreate,
    QueueUpdate,
    QueueRead,
    QueueItemCreate,
    QueueItemUpdate,
    QueueItemRead,
    QueueItemReorderRequest,
    QueueReleaseRequest,
    serialize_queue,
    serialize_queue_item,
)
from app.api import resource_access
from app.core.tools import Tool
from app.db.session import require_actor_context
from app.services import permissions as permissions_service
from app.services.tenant import queues as queues_service
from app.services.tenant import tags as tags_service
from app.schemas.tenant.tag import TagSetRequest
from app.services.content_sockets import sockets
from app.api.content_socket import serve_tool_stream


async def _queue_item_attachments(
    session: AsyncSession, item: QueueItem
) -> tuple[list[Related], list[Related]]:
    """The documents and tasks pinned to one queue item."""
    endpoint = relationships.Endpoint(SearchEntityType.queue_item, item.id)
    documents = await relationships.related_for(
        session,
        endpoint,
        relationship_type=RelationshipType.attached,
        other_kind=SearchEntityType.document,
        model=Document,
    )
    tasks = await relationships.related_for(
        session,
        endpoint,
        relationship_type=RelationshipType.attached,
        other_kind=SearchEntityType.task,
        model=Task,
    )
    return documents, tasks


async def _serialized_queue(
    session: AsyncSession, queue: Queue, *, user_id: int | None
) -> QueueRead:
    """A queue and its items, each with what is pinned to it.

    ``serialize_queue`` takes no session, so nothing fetched the attachments for
    a queue read as a whole and every item came back with none — which is what
    a reader sees when they open a queue rather than one item of it.

    Batched rather than per item: two queries for the documents on the whole
    page and two for the tasks, however many items the queue holds.
    """
    items = getattr(queue, "items", None) or []
    item_ids = [item.id for item in items]
    documents = await relationships.related_for_many(
        session,
        SearchEntityType.queue_item,
        item_ids,
        relationship_type=RelationshipType.attached,
        other_kind=SearchEntityType.document,
        model=Document,
    )
    tasks = await relationships.related_for_many(
        session,
        SearchEntityType.queue_item,
        item_ids,
        relationship_type=RelationshipType.attached,
        other_kind=SearchEntityType.task,
        model=Task,
    )
    # Counted over every kind, not summed from the two above: an item may be
    # pinned to any of the fourteen.
    counts = await relationships.counts_for_many(
        session,
        SearchEntityType.queue_item,
        item_ids,
        relationship_type=RelationshipType.attached,
    )
    return serialize_queue(
        queue,
        context=require_actor_context(session),
        user_id=user_id,
        documents=documents,
        tasks=tasks,
        attachment_counts=counts,
    )


async def _serialized_queue_item(
    session: AsyncSession, item: QueueItem
) -> QueueItemRead:
    documents, tasks = await _queue_item_attachments(session, item)
    counts = await relationships.counts_for_many(
        session,
        SearchEntityType.queue_item,
        [item.id],
        relationship_type=RelationshipType.attached,
    )
    return serialize_queue_item(
        item,
        documents=documents,
        tasks=tasks,
        attachment_count=counts.get(item.id, 0),
    )


router = APIRouter(route_class=ActorRoute)

#: Flat read-back route, mounted at the guild root. An event envelope names
#: ``(resource_type, id)`` and nothing else, so the resource has to be
#: addressable by its own id — a nested path would need a parent the envelope
#: never carries. Writes stay nested under their queue, where the caller is
#: already working inside one.
items_router = APIRouter(route_class=ActorRoute)


logger = logging.getLogger(__name__)

GuildContextDep = Annotated[GuildContext, Depends(get_guild_membership)]
#: The routes an installed app may call, under the queues scopes. A queue's
#: items and its turn commands answer to the queue's own scopes.
QueuesRead = Annotated[ActorContext, Depends(app_scope("queues:read"))]
QueuesWrite = Annotated[ActorContext, Depends(app_scope("queues:write"))]


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


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


async def _refetch_queue(
    session: RLSSessionDep,
    queue_id: int,
) -> Queue:
    """Re-fetch a queue after commit for serialization.

    Uses populate_existing=True so selectinload returns fresh relationship data
    (needed because expire_on_commit=False keeps stale collections in identity map).
    """
    queue = await queues_service.get_queue(session, queue_id, populate_existing=True)
    if not queue:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=Tool.queue.not_found_code,
        )
    return queue


# ---------------------------------------------------------------------------
# Queue CRUD
# ---------------------------------------------------------------------------


@items_router.get("/queue-items/{item_id}", response_model=QueueItemRead)
async def read_queue_item(
    item_id: int,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: QueuesRead,
    include_deleted: IncludeDeletedDep = False,
) -> QueueItemRead:
    """One queue item by id — the read-back for a ``queue_items.*`` event.

    Gated by read access on the queue it belongs to, like listing it. The item's
    own id is the whole address, so there is no parent to mismatch.
    """
    item = await queues_service.get_queue_item(session, item_id)
    if not item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=QueueMessages.ITEM_NOT_FOUND,
        )
    await resource_access.load_authorized(
        session, Tool.queue, item.queue_id, current_user, guild_context, access="read"
    )
    return await _serialized_queue_item(session, item)


@router.get("/{queue_id}", response_model=QueueRead)
async def read_queue(
    queue_id: int,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: QueuesRead,
    include_deleted: IncludeDeletedDep = False,
) -> QueueRead:
    queue = await resource_access.load_authorized(
        session, Tool.queue, queue_id, current_user, guild_context
    )
    return await _serialized_queue(session, queue, user_id=guild_context.user_id)


@router.post("/", response_model=QueueRead, status_code=status.HTTP_201_CREATED)
async def create_queue(
    queue_in: QueueCreate,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: QueuesWrite,
) -> QueueRead:
    """Create a new queue in an initiative.

    Requires create_queues permission on the initiative (or guild admin).
    The creator automatically gets owner-level permission.
    """
    resource_access.refuse_app_sharing(guild_context, queue_in, "grants")
    initiative = await resource_access.prepare_create(
        session, Tool.queue, queue_in.initiative_id, current_user, guild_context
    )

    queue = Queue(
        initiative_id=initiative.id,
        created_by=guild_context.user_id,
        name=queue_in.name.strip(),
        description=queue_in.description,
    )
    session.add(queue)
    await session.flush()

    await resource_access.grant_initial_sharing(
        session,
        guild_context,
        Tool.queue,
        user=current_user,
        resource_id=queue.id,
        initiative_id=queue.initiative_id,
        payload=queue_in,
        grants=queue_in.grants,
    )
    await session.commit()

    hydrated = await _refetch_queue(session, queue.id)
    return await _serialized_queue(session, hydrated, user_id=guild_context.user_id)


@router.patch("/{queue_id}", response_model=QueueRead)
async def update_queue(
    queue_id: int,
    queue_in: QueueUpdate,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: QueuesWrite,
) -> QueueRead:
    """Update queue name/description. Requires write access."""
    queue = await resource_access.load_authorized(
        session, Tool.queue, queue_id, current_user, guild_context, access="write"
    )
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

    hydrated = await _refetch_queue(session, queue.id)
    result = await _serialized_queue(session, hydrated, user_id=guild_context.user_id)
    if updated:
        sockets.signal(routed_guild_id(session), Tool.queue, queue_id, "queue_updated")
    return result


@router.delete("/{queue_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_queue(
    queue_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> None:
    """Soft-delete a queue. Cascades to its items. Requires owner permission
    or guild admin."""
    from app.services.tenant.soft_delete import trash

    queue = await resource_access.load_authorized(
        session, Tool.queue, queue_id, current_user, guild_context, access="read"
    )
    permissions_service.require_access(
        permissions_service.DAC_RESOURCES[Tool.queue],
        queue,
        require_owner=True,
        context=guild_context,
    )
    await trash(
        session,
        queue,
        deleted_by_user_id=current_user.id,
    )
    await session.commit()
    sockets.signal(guild_context.guild_id, Tool.queue, queue_id, "queue_deleted")


# ---------------------------------------------------------------------------
# Queue Items
# ---------------------------------------------------------------------------


@router.post(
    "/{queue_id}/items",
    response_model=QueueItemRead,
    status_code=status.HTTP_201_CREATED,
)
async def add_queue_item(
    queue_id: int,
    item_in: QueueItemCreate,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> QueueItemRead:
    """Add an item to a queue. Requires write access."""
    queue = await resource_access.load_authorized(
        session, Tool.queue, queue_id, current_user, guild_context, access="write"
    )

    item = QueueItem(
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
        await tags_service.set_entity_tags(
            session,
            tags_service.TAG_LINKS["queue_item"],
            guild_id=routed_guild_id(session),
            entity_id=item.id,
            tag_ids=item_in.tag_ids,
        )

    # Set document links if provided
    if item_in.document_ids:
        await queues_service.set_queue_item_documents(
            session,
            item,
            item_in.document_ids,
            routed_guild_id(session),
            current_user.id,
        )

    # Set task links if provided
    if item_in.task_ids:
        await queues_service.set_queue_item_tasks(
            session,
            item,
            item_in.task_ids,
            routed_guild_id(session),
            current_user.id,
        )

    await session.commit()

    hydrated_item = await queues_service.get_queue_item(
        session, item.id, populate_existing=True
    )
    if not hydrated_item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=QueueMessages.ITEM_NOT_FOUND,
        )
    result = await _serialized_queue_item(session, hydrated_item)
    sockets.signal(routed_guild_id(session), Tool.queue, queue_id, "item_added")
    return result


@router.patch("/{queue_id}/items/{item_id}", response_model=QueueItemRead)
async def update_queue_item(
    queue_id: int,
    item_id: int,
    item_in: QueueItemUpdate,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: QueuesWrite,
) -> QueueItemRead:
    """Update a queue item. Requires write access on the queue."""
    await resource_access.load_authorized(
        session, Tool.queue, queue_id, current_user, guild_context, access="write"
    )
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

    hydrated_item = await queues_service.get_queue_item(
        session, item.id, populate_existing=True
    )
    if not hydrated_item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=QueueMessages.ITEM_NOT_FOUND,
        )
    result = await _serialized_queue_item(session, hydrated_item)
    sockets.signal(routed_guild_id(session), Tool.queue, queue_id, "item_updated")
    return result


@router.delete("/{queue_id}/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_queue_item(
    queue_id: int,
    item_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> None:
    """Soft-delete a queue item. Requires write access on the parent queue."""
    from app.services.tenant.soft_delete import trash

    queue = await resource_access.load_authorized(
        session, Tool.queue, queue_id, current_user, guild_context, access="write"
    )
    item = await _get_item_for_queue(session, queue_id, item_id)

    if queue.current_item_id == item.id:
        queue.current_item_id = None
        session.add(queue)

    await trash(
        session,
        item,
        deleted_by_user_id=current_user.id,
    )
    await session.commit()
    sockets.signal(routed_guild_id(session), Tool.queue, queue_id, "item_removed")


@router.put("/{queue_id}/items/reorder", response_model=QueueRead)
async def reorder_queue_items(
    queue_id: int,
    reorder_in: QueueItemReorderRequest,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> QueueRead:
    """Bulk reorder queue items. Requires write access."""
    queue = await resource_access.load_authorized(
        session, Tool.queue, queue_id, current_user, guild_context, access="write"
    )

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

    hydrated = await _refetch_queue(session, queue.id)
    result = await _serialized_queue(session, hydrated, user_id=current_user.id)
    sockets.signal(routed_guild_id(session), Tool.queue, queue_id, "items_reordered")
    return result


# ---------------------------------------------------------------------------
# Turn Management
# ---------------------------------------------------------------------------


@router.post("/{queue_id}/start", response_model=QueueRead)
async def start_queue(
    queue_id: int,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: QueuesWrite,
) -> QueueRead:
    """Start the queue: set active, reset to first item, round 1."""
    queue = await resource_access.load_authorized(
        session, Tool.queue, queue_id, current_user, guild_context, access="write"
    )
    await queues_service.start_queue(session, queue)
    await session.commit()

    hydrated = await _refetch_queue(session, queue.id)
    result = await _serialized_queue(session, hydrated, user_id=guild_context.user_id)
    sockets.signal(routed_guild_id(session), Tool.queue, queue_id, "queue_started")
    return result


@router.post("/{queue_id}/stop", response_model=QueueRead)
async def stop_queue(
    queue_id: int,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: QueuesWrite,
) -> QueueRead:
    """Stop the queue: set inactive but keep current position."""
    queue = await resource_access.load_authorized(
        session, Tool.queue, queue_id, current_user, guild_context, access="write"
    )
    await queues_service.stop_queue(session, queue)
    await session.commit()

    hydrated = await _refetch_queue(session, queue.id)
    result = await _serialized_queue(session, hydrated, user_id=guild_context.user_id)
    sockets.signal(routed_guild_id(session), Tool.queue, queue_id, "queue_stopped")
    return result


@router.post("/{queue_id}/next", response_model=QueueRead)
async def advance_turn(
    queue_id: int,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: QueuesWrite,
) -> QueueRead:
    """Advance to the next visible item. Wraps around and increments round."""
    queue = await resource_access.load_authorized(
        session, Tool.queue, queue_id, current_user, guild_context, access="write"
    )
    await queues_service.advance_turn(session, queue)
    await session.commit()

    hydrated = await _refetch_queue(session, queue.id)
    result = await _serialized_queue(session, hydrated, user_id=guild_context.user_id)
    sockets.signal(routed_guild_id(session), Tool.queue, queue_id, "turn_advance")
    return result


@router.post("/{queue_id}/previous", response_model=QueueRead)
async def previous_turn(
    queue_id: int,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: QueuesWrite,
) -> QueueRead:
    """Move to the previous visible item. Wraps around and decrements round."""
    queue = await resource_access.load_authorized(
        session, Tool.queue, queue_id, current_user, guild_context, access="write"
    )
    await queues_service.previous_turn(session, queue)
    await session.commit()

    hydrated = await _refetch_queue(session, queue.id)
    result = await _serialized_queue(session, hydrated, user_id=guild_context.user_id)
    sockets.signal(routed_guild_id(session), Tool.queue, queue_id, "turn_previous")
    return result


@router.post("/{queue_id}/set-active/{item_id}", response_model=QueueRead)
async def set_active_item(
    queue_id: int,
    item_id: int,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: QueuesWrite,
) -> QueueRead:
    """Jump to a specific item in the queue."""
    queue = await resource_access.load_authorized(
        session, Tool.queue, queue_id, current_user, guild_context, access="write"
    )
    await queues_service.set_active_item(session, queue, item_id)
    await session.commit()

    hydrated = await _refetch_queue(session, queue.id)
    result = await _serialized_queue(session, hydrated, user_id=guild_context.user_id)
    sockets.signal(routed_guild_id(session), Tool.queue, queue_id, "turn_set_active")
    return result


@router.post("/{queue_id}/reset", response_model=QueueRead)
async def reset_queue(
    queue_id: int,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: QueuesWrite,
) -> QueueRead:
    """Reset the queue to round 1, first visible item."""
    queue = await resource_access.load_authorized(
        session, Tool.queue, queue_id, current_user, guild_context, access="write"
    )
    await queues_service.reset_queue(session, queue)
    await session.commit()

    hydrated = await _refetch_queue(session, queue.id)
    result = await _serialized_queue(session, hydrated, user_id=guild_context.user_id)
    sockets.signal(routed_guild_id(session), Tool.queue, queue_id, "queue_reset")
    return result


@router.post("/{queue_id}/hold", response_model=QueueRead)
async def hold_current_turn(
    queue_id: int,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: QueuesWrite,
) -> QueueRead:
    """Hold the current turn — the item leaves the rotation until it acts.

    The held item is recorded with the current round; the rotation
    auto-releases it when its natural position-desc slot comes back around in
    a later round. Users can also call ``/release/{item_id}`` to act sooner.
    """
    queue = await resource_access.load_authorized(
        session, Tool.queue, queue_id, current_user, guild_context, access="write"
    )
    await queues_service.hold_current(session, queue)
    await session.commit()

    hydrated = await _refetch_queue(session, queue.id)
    result = await _serialized_queue(session, hydrated, user_id=guild_context.user_id)
    sockets.signal(routed_guild_id(session), Tool.queue, queue_id, "turn_held")
    return result


@router.post("/{queue_id}/release/{item_id}", response_model=QueueRead)
async def release_held_item(
    queue_id: int,
    item_id: int,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: QueuesWrite,
    options: QueueReleaseRequest = QueueReleaseRequest(),  # noqa: B008
) -> QueueRead:
    """Release a held item back into the rotation.

    Clears ``held_at_round`` on the target so it rejoins the active rotation.
    The rotation pointer is unchanged, so this doesn't pull current back onto
    items that already took their turn this round.

    When ``options.reposition`` is True (PF2e Delay semantics), the released
    item's ``position`` is rewritten to land just after the current item in
    turn order — the new initiative slot persists for the rest of the
    encounter. Default ``False`` keeps the released item at its original
    position so it acts at its natural slot next time the rotation reaches
    it.
    """
    queue = await resource_access.load_authorized(
        session, Tool.queue, queue_id, current_user, guild_context, access="write"
    )
    await queues_service.release_held(
        session, queue, item_id, reposition=options.reposition
    )
    await session.commit()

    hydrated = await _refetch_queue(session, queue.id)
    result = await _serialized_queue(session, hydrated, user_id=guild_context.user_id)
    sockets.signal(routed_guild_id(session), Tool.queue, queue_id, "turn_released")
    return result


# ---------------------------------------------------------------------------
# Item Tags
# ---------------------------------------------------------------------------


@router.put("/{queue_id}/items/{item_id}/tags", response_model=QueueItemRead)
async def set_queue_item_tags(
    queue_id: int,
    item_id: int,
    tags_in: TagSetRequest,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> QueueItemRead:
    """Set tags on a queue item. Replaces all existing tags."""
    await resource_access.load_authorized(
        session, Tool.queue, queue_id, current_user, guild_context, access="write"
    )
    item = await _get_item_for_queue(session, queue_id, item_id)

    await tags_service.set_entity_tags(
        session,
        tags_service.TAG_LINKS["queue_item"],
        guild_id=routed_guild_id(session),
        entity_id=item.id,
        tag_ids=tags_in.tag_ids,
    )
    await session.commit()

    hydrated_item = await queues_service.get_queue_item(
        session, item.id, populate_existing=True
    )
    if not hydrated_item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=QueueMessages.ITEM_NOT_FOUND,
        )
    result = await _serialized_queue_item(session, hydrated_item)
    sockets.signal(routed_guild_id(session), Tool.queue, queue_id, "tags_changed")
    return result


# ---------------------------------------------------------------------------
# Item Attachments (documents, tasks)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Sharing (resource grants)
# ---------------------------------------------------------------------------


async def read_after_write(
    session: RLSSessionDep,
    queue_id: int,
    user: Optional[User],
    guild_context: ActorContext,
) -> QueueRead:
    """The queue a write answers with: re-read after the commit, serialized.

    Registered in ``tool_lists.TOOL_LISTS`` so the shared sharing route
    (``tool_grants.py``) answers in this tool's own shape.
    """
    hydrated = await _refetch_queue(session, queue_id)
    return await _serialized_queue(session, hydrated, user_id=guild_context.user_id)


# ---------------------------------------------------------------------------
# WebSocket
# ---------------------------------------------------------------------------


@router.websocket("/{queue_id}/ws")
async def websocket_queue(websocket: WebSocket, guild_id: int, queue_id: int) -> None:
    """Change signals for one queue: ``{type, id, timestamp}`` frames and a
    heartbeat. The client refetches on each; see ``serve_tool_stream``."""
    await serve_tool_stream(websocket, guild_id, Tool.queue, queue_id)
