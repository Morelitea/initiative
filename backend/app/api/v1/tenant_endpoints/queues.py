"""Queue endpoints — CRUD, turn management, item management, and DAC permissions.

Initiative-scoped queues for turn/priority tracking (e.g., TTRPG initiative order).
Follows the document endpoint patterns for RLS, DAC, and initiative permission checks.
"""

from datetime import datetime, timezone
from typing import Annotated, Optional

import json
import logging

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from sqlalchemy.orm import selectinload
from sqlmodel import select

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import routed_guild_id
from app.core.relationships import Related, RelationshipType
from app.core.search import SearchEntityType
from app.models.tenant.document import Document
from app.models.tenant.task import Task
from app.services.tenant import relationships
from app.core.auth_context import satisfied_provider_ids
from app.api.deps import (
    IncludeDeletedDep,
    RLSSessionDep,
    establish_guild_access,
    get_current_active_user,
    get_guild_membership,
    GuildAccessError,
    GuildContext,
)
from app.core.security import SESSION_COOKIE_NAME
from app.db.session import AsyncSessionLocal
from app.models.tenant.queue import (
    Queue,
    QueueItem,
)
from app.models.tenant.resource_grant import ResourceGrant, ResourceAccessLevel
from app.models.tenant.initiative import (
    Initiative,
)
from app.models.platform.user import User
from app.core.messages import QueueMessages, InitiativeMessages
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
from app.db.session import require_guild_context
from app.services import permissions as permissions_service
from app.services.tenant import queues as queues_service
from app.services.tenant import tags as tags_service
from app.schemas.tenant.tag import TagSetRequest
from app.services.stream_authz import authority as stream_authority
from app.services.platform.ws_auth import authenticate_ws_token


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
    session: AsyncSession, queue: Queue, *, user_id: int
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
        context=require_guild_context(session),
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


router = APIRouter()

#: Flat read-back route, mounted at the guild root. An event envelope names
#: ``(resource_type, id)`` and nothing else, so the resource has to be
#: addressable by its own id — a nested path would need a parent the envelope
#: never carries. Writes stay nested under their queue, where the caller is
#: already working inside one.
items_router = APIRouter()


logger = logging.getLogger(__name__)

GuildContextDep = Annotated[GuildContext, Depends(get_guild_membership)]


async def _emit_queue(
    session,
    queue_id: int,
    event_type: str,
    data: dict,
    *,
    guild_id: int | None = None,
) -> None:
    """Fan a queue event out through the streaming spine, guild-namespaced.

    Pass ``guild_id`` when the caller already holds it — required for the delete
    path, where the row is soft-deleted before this runs so a post-commit lookup
    would hit the global ``deleted_at IS NULL`` filter and find nothing, silently
    dropping the ``queue_deleted`` event. Otherwise the queue's guild is resolved
    from the (guild-routed) session (context replays automatically after a
    commit). One streaming spine; rooms are guild-namespaced (queue ids are
    per-schema)."""
    if guild_id is None:
        guild_id = routed_guild_id(session)
        if guild_id is None:
            return
    await stream_authority.emit(guild_id, "queue", queue_id, event_type, data)


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
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
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
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
    include_deleted: IncludeDeletedDep = False,
) -> QueueRead:
    queue = await resource_access.load_authorized(
        session, Tool.queue, queue_id, current_user, guild_context
    )
    return await _serialized_queue(session, queue, user_id=current_user.id)


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
            detail=Tool.queue.feature_disabled_code,
        )
    await resource_access.require_create(
        session, Tool.queue, initiative, current_user, guild_context
    )

    queue = Queue(
        initiative_id=initiative.id,
        created_by=current_user.id,
        name=queue_in.name.strip(),
        description=queue_in.description,
    )
    session.add(queue)
    await session.flush()

    # Owner permission for the creator
    owner_perm = ResourceGrant(
        resource_type="queue",
        resource_id=queue.id,
        user_id=current_user.id,
        role_id=None,
        level=ResourceAccessLevel.owner,
        initiative_id=queue.initiative_id,
    )
    session.add(owner_perm)

    # Apply the initial sharing exactly the way edits do — one grant list, one
    # code path (empty default = owner-only until shared).
    await permissions_service.replace_resource_grants(
        session,
        resource_type="queue",
        resource_id=queue.id,
        guild_id=guild_context.guild_id,
        initiative_id=queue.initiative_id,
        owner_id=current_user.id,
        grants=queue_in.grants,
        actor_user_id=current_user.id,
    )

    await session.commit()

    hydrated = await _refetch_queue(session, queue.id)
    return await _serialized_queue(session, hydrated, user_id=current_user.id)


@router.patch("/{queue_id}", response_model=QueueRead)
async def update_queue(
    queue_id: int,
    queue_in: QueueUpdate,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
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
    result = await _serialized_queue(session, hydrated, user_id=current_user.id)
    if updated:
        await _emit_queue(
            session, queue_id, "queue_updated", result.model_dump(mode="json")
        )
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
    from app.services.platform import guilds as guilds_service
    from app.services.tenant.soft_delete import soft_delete_entity

    queue = await resource_access.load_authorized(
        session, Tool.queue, queue_id, current_user, guild_context, access="read"
    )
    permissions_service.require_access(
        permissions_service.DAC_RESOURCES[Tool.queue],
        queue,
        current_user,
        require_owner=True,
        context=guild_context,
    )
    retention_days = await guilds_service.get_guild_retention_days(
        session, guild_context.guild_id
    )
    await soft_delete_entity(
        session,
        queue,
        deleted_by_user_id=current_user.id,
        retention_days=retention_days,
    )
    await session.commit()
    # Pass guild_id explicitly: the queue is soft-deleted, so _emit_queue's
    # fallback lookup (deleted_at IS NULL filtered) would find nothing and drop
    # the event.
    await _emit_queue(
        session,
        queue_id,
        "queue_deleted",
        {"id": queue_id},
        guild_id=guild_context.guild_id,
    )


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
    await _emit_queue(session, queue_id, "item_added", result.model_dump(mode="json"))
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
    await _emit_queue(session, queue_id, "item_updated", result.model_dump(mode="json"))
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
    from app.services.platform import guilds as guilds_service
    from app.services.tenant.soft_delete import soft_delete_entity

    queue = await resource_access.load_authorized(
        session, Tool.queue, queue_id, current_user, guild_context, access="write"
    )
    item = await _get_item_for_queue(session, queue_id, item_id)

    if queue.current_item_id == item.id:
        queue.current_item_id = None
        session.add(queue)

    retention_days = await guilds_service.get_guild_retention_days(
        session, guild_context.guild_id
    )
    await soft_delete_entity(
        session,
        item,
        deleted_by_user_id=current_user.id,
        retention_days=retention_days,
    )
    await session.commit()
    await _emit_queue(session, queue_id, "item_removed", {"id": item_id})


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
    await _emit_queue(
        session, queue_id, "items_reordered", result.model_dump(mode="json")
    )
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
    queue = await resource_access.load_authorized(
        session, Tool.queue, queue_id, current_user, guild_context, access="write"
    )
    await queues_service.start_queue(session, queue)
    await session.commit()

    hydrated = await _refetch_queue(session, queue.id)
    result = await _serialized_queue(session, hydrated, user_id=current_user.id)
    await _emit_queue(
        session, queue_id, "queue_started", result.model_dump(mode="json")
    )
    return result


@router.post("/{queue_id}/stop", response_model=QueueRead)
async def stop_queue(
    queue_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> QueueRead:
    """Stop the queue: set inactive but keep current position."""
    queue = await resource_access.load_authorized(
        session, Tool.queue, queue_id, current_user, guild_context, access="write"
    )
    await queues_service.stop_queue(session, queue)
    await session.commit()

    hydrated = await _refetch_queue(session, queue.id)
    result = await _serialized_queue(session, hydrated, user_id=current_user.id)
    await _emit_queue(
        session, queue_id, "queue_stopped", result.model_dump(mode="json")
    )
    return result


@router.post("/{queue_id}/next", response_model=QueueRead)
async def advance_turn(
    queue_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> QueueRead:
    """Advance to the next visible item. Wraps around and increments round."""
    queue = await resource_access.load_authorized(
        session, Tool.queue, queue_id, current_user, guild_context, access="write"
    )
    await queues_service.advance_turn(session, queue)
    await session.commit()

    hydrated = await _refetch_queue(session, queue.id)
    result = await _serialized_queue(session, hydrated, user_id=current_user.id)
    await _emit_queue(session, queue_id, "turn_advance", result.model_dump(mode="json"))
    return result


@router.post("/{queue_id}/previous", response_model=QueueRead)
async def previous_turn(
    queue_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> QueueRead:
    """Move to the previous visible item. Wraps around and decrements round."""
    queue = await resource_access.load_authorized(
        session, Tool.queue, queue_id, current_user, guild_context, access="write"
    )
    await queues_service.previous_turn(session, queue)
    await session.commit()

    hydrated = await _refetch_queue(session, queue.id)
    result = await _serialized_queue(session, hydrated, user_id=current_user.id)
    await _emit_queue(
        session, queue_id, "turn_previous", result.model_dump(mode="json")
    )
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
    queue = await resource_access.load_authorized(
        session, Tool.queue, queue_id, current_user, guild_context, access="write"
    )
    await queues_service.set_active_item(session, queue, item_id)
    await session.commit()

    hydrated = await _refetch_queue(session, queue.id)
    result = await _serialized_queue(session, hydrated, user_id=current_user.id)
    await _emit_queue(
        session, queue_id, "turn_set_active", result.model_dump(mode="json")
    )
    return result


@router.post("/{queue_id}/reset", response_model=QueueRead)
async def reset_queue(
    queue_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> QueueRead:
    """Reset the queue to round 1, first visible item."""
    queue = await resource_access.load_authorized(
        session, Tool.queue, queue_id, current_user, guild_context, access="write"
    )
    await queues_service.reset_queue(session, queue)
    await session.commit()

    hydrated = await _refetch_queue(session, queue.id)
    result = await _serialized_queue(session, hydrated, user_id=current_user.id)
    await _emit_queue(session, queue_id, "queue_reset", result.model_dump(mode="json"))
    return result


@router.post("/{queue_id}/hold", response_model=QueueRead)
async def hold_current_turn(
    queue_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
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
    result = await _serialized_queue(session, hydrated, user_id=current_user.id)
    await _emit_queue(session, queue_id, "turn_held", result.model_dump(mode="json"))
    return result


@router.post("/{queue_id}/release/{item_id}", response_model=QueueRead)
async def release_held_item(
    queue_id: int,
    item_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
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
    result = await _serialized_queue(session, hydrated, user_id=current_user.id)
    await _emit_queue(
        session, queue_id, "turn_released", result.model_dump(mode="json")
    )
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
    await _emit_queue(session, queue_id, "tags_changed", result.model_dump(mode="json"))
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
    user: User,
    guild_context: GuildContext,
) -> QueueRead:
    """The queue a write answers with: re-read after the commit, serialized.

    Registered in ``tool_lists.TOOL_LISTS`` so the shared sharing route
    (``tool_grants.py``) answers in this tool's own shape.
    """
    hydrated = await _refetch_queue(session, queue_id)
    return await _serialized_queue(session, hydrated, user_id=user.id)


# ---------------------------------------------------------------------------
# WebSocket — Real-time queue updates
# ---------------------------------------------------------------------------


async def _ws_authenticate(token: str, session) -> Optional[User]:
    """Validate a session JWT or device token and return the user, or None.

    Delegates to the shared ``authenticate_ws_token`` helper so the
    ``token_version`` revocation check stays in lockstep with the HTTP auth
    path and the other realtime WebSocket endpoints (SEC-4).
    """
    return await authenticate_ws_token(token, session)


@router.websocket("/{queue_id}/ws")
async def websocket_queue(
    websocket: WebSocket,
    guild_id: int,
    queue_id: int,
) -> None:
    """WebSocket for real-time queue updates (server-to-client broadcast).

    Protocol:
    1. Client connects and sends JSON: {"token": "..."} — the guild comes
       from the ``/g/{guild_id}`` path segment
    2. Server validates auth and initiative membership
    3. Server broadcasts JSON events as queue state changes
    4. Client keeps connection alive; no client-to-server data expected

    Event types: turn_advance, turn_previous, turn_set_active, turn_held,
    turn_released, item_added, item_removed, item_updated, tags_changed,
    queue_started, queue_stopped, queue_reset, items_reordered,
    queue_updated, queue_deleted, documents_changed, tasks_changed,
    permissions_changed
    """
    await websocket.accept()

    # Wait for auth message
    try:
        raw = await websocket.receive_text()
        auth_payload = json.loads(raw)
        token = auth_payload.get("token")
        if not token:
            token = websocket.cookies.get(SESSION_COOKIE_NAME)
        if not token:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return
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

        # Establish guild access through the single entry point (membership /
        # live PAM grant / break-glass) — same gate and applied context as REST
        # and the other sockets. Previously a membership-only check, so a PAM
        # grantee or break-glass admin couldn't subscribe.
        try:
            await establish_guild_access(session, user, guild_id)
        except GuildAccessError:
            logger.warning(
                f"Queue WS: user {user.id} has no access to guild {guild_id}"
            )
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

        # Fetch queue and check DAC
        queue = await queues_service.get_queue(session, queue_id)
        if not queue or routed_guild_id(session) != guild_id:
            logger.warning(f"Queue WS: queue {queue_id} not found in guild {guild_id}")
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

        # DAC level via the shared engine; the guild-admin / break-glass bypass is
        # applied inside compute_* through the active role context that
        # establish_guild_access set, so no separate admin check is needed.
        level = permissions_service.compute_permission(
            permissions_service.DAC_RESOURCES[Tool.queue],
            queue,
            user.id,
            context=require_guild_context(session),
        )
        if level is None:
            logger.warning(
                f"Queue WS: user {user.id} has no access to queue {queue_id}"
            )
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

    logger.info(f"Queue WS: user {user.id} joined queue {queue_id}")

    # The streaming spine owns the socket lifecycle, fan-out, and continuous,
    # every-level re-authorization: a grant / membership / role / PAM change
    # disconnects this socket — immediately for guild/initiative-level removal
    # (revoke_user), within the bounded interval for within-initiative DAC. The
    # check re-runs the full join (establish_guild_access → load the queue under
    # RLS → DAC).
    async def _authorize(check_session, check_user):
        q = await queues_service.get_queue(check_session, queue_id)
        if q is None:
            return False
        return (
            permissions_service.compute_permission(
                permissions_service.DAC_RESOURCES[Tool.queue],
                q,
                check_user.id,
                context=require_guild_context(check_session),
            )
            is not None
        )

    await stream_authority.join(
        websocket,
        user,
        guild_id=guild_id,
        initiative_id=queue.initiative_id,
        resource_type="queue",
        resource_id=queue_id,
        authorize=_authorize,
        satisfied_providers=satisfied_provider_ids(),
    )

    try:
        # Keep the connection alive — listen for pings/disconnects
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await stream_authority.leave(websocket)
        logger.info(f"Queue WS: user {user.id} left queue {queue_id}")
