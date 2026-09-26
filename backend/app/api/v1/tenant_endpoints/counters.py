"""Counter group endpoints — CRUD, value operations, permissions, WebSocket."""

from datetime import datetime, timezone
from decimal import Decimal
from typing import Annotated, Optional

import logging

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    WebSocket,
    status,
)

from app.db.session import routed_guild_id
from app.api.actor_route import ActorRoute
from app.api.deps import (
    ActorContext,
    ActorSessionDep,
    ActorUserDep,
    IncludeDeletedDep,
    RLSSessionDep,
    app_scope,
    get_current_active_user,
    GuildContextDep,
)
from app.core.messages import CounterMessages
from app.models.tenant.counter import (
    Counter,
    CounterGroup,
    CounterViewMode,
)
from app.models.platform.user import User
from app.schemas.tenant.counter import (
    CounterCreate,
    CounterGroupCreate,
    CounterGroupDuplicateRequest,
    CounterGroupRead,
    CounterGroupUpdate,
    CounterRead,
    CounterSetCountRequest,
    CounterSortRequest,
    CounterUpdate,
    serialize_counter,
    serialize_counter_group,
    _validate_counter_constraints,
)
from app.services.permissions import Action
from app.services.tenant import counters as counters_service
from app.api import resource_access
from app.core.tools import Tool
from app.services.content_sockets import sockets
from app.api.content_socket import serve_tool_stream


router = APIRouter(route_class=ActorRoute)

#: Flat read-back route, mounted at the guild root. An event envelope names
#: ``(resource_type, id)`` and nothing else, so the resource has to be
#: addressable by its own id — a nested path would need a parent the envelope
#: never carries. Writes stay nested under their group, where the caller is
#: already working inside one.
counters_router = APIRouter(route_class=ActorRoute)
logger = logging.getLogger(__name__)

#: The routes an installed app may call, under the counter groups scopes. A
#: group's counters and their commands answer to the group's own scopes.
CounterGroupsRead = Annotated[ActorContext, Depends(app_scope("counter_groups:read"))]
CounterGroupsWrite = Annotated[ActorContext, Depends(app_scope("counter_groups:write"))]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _get_counter_for_group(
    session: RLSSessionDep,
    group_id: int,
    counter_id: int,
) -> Counter:
    counter = await counters_service.get_counter(session, counter_id)
    if (
        not counter
        or counter.counter_group_id != group_id
        or counter.deleted_at is not None
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=CounterMessages.NOT_FOUND,
        )
    return counter


async def _refetch_group(session: RLSSessionDep, group_id: int) -> CounterGroup:
    group = await counters_service.get_counter_group(
        session, group_id, populate_existing=True
    )
    if not group:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=Tool.counter_group.not_found_code,
        )
    return group


# ---------------------------------------------------------------------------
# Counter Group CRUD
# ---------------------------------------------------------------------------


@router.get("/{group_id}", response_model=CounterGroupRead)
async def read_counter_group(
    group_id: int,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: CounterGroupsRead,
    include_deleted: IncludeDeletedDep = False,
) -> CounterGroupRead:
    group = await resource_access.load_authorized(
        session, Tool.counter_group, group_id, current_user, guild_context
    )
    return serialize_counter_group(
        group,
        user_id=guild_context.user_id,
        context=guild_context,
    )


@router.post("/", response_model=CounterGroupRead, status_code=status.HTTP_201_CREATED)
async def create_counter_group(
    group_in: CounterGroupCreate,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: CounterGroupsWrite,
) -> CounterGroupRead:
    resource_access.refuse_app_sharing(guild_context, group_in, "grants")
    initiative = await resource_access.prepare_create(
        session, Tool.counter_group, group_in.initiative_id, current_user, guild_context
    )

    group = CounterGroup(
        initiative_id=initiative.id,
        created_by=guild_context.user_id,
        name=group_in.name.strip(),
        description=group_in.description,
    )
    session.add(group)
    await session.flush()
    await resource_access.grant_initial_sharing(
        session,
        guild_context,
        Tool.counter_group,
        user=current_user,
        resource_id=group.id,
        initiative_id=group.initiative_id,
        payload=group_in,
        grants=group_in.grants,
    )
    await session.commit()

    hydrated = await _refetch_group(session, group.id)
    return serialize_counter_group(
        hydrated,
        user_id=guild_context.user_id,
        context=guild_context,
    )


@router.post(
    "/{group_id}/duplicate",
    response_model=CounterGroupRead,
    status_code=status.HTTP_201_CREATED,
)
async def duplicate_counter_group(
    group_id: int,
    payload: CounterGroupDuplicateRequest,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> CounterGroupRead:
    source = await resource_access.load_authorized(
        session,
        Tool.counter_group,
        group_id,
        current_user,
        guild_context,
        access="write",
    )
    await resource_access.prepare_create(
        session, Tool.counter_group, source.initiative_id, current_user, guild_context
    )

    new_group = CounterGroup(
        initiative_id=source.initiative_id,
        created_by=current_user.id,
        name=(
            payload.name.strip()
            if payload.name and payload.name.strip()
            else f"{source.name} (Copy)"
        ),
        description=source.description,
    )
    session.add(new_group)
    await session.flush()
    await resource_access.grant_initial_sharing(
        session,
        guild_context,
        Tool.counter_group,
        user=current_user,
        resource_id=new_group.id,
        initiative_id=new_group.initiative_id,
        payload=payload,
        grants=resource_access.duplicate_sharing(
            source, initiative_id=source.initiative_id
        ),
    )
    await counters_service.copy_counters(session, source, new_group)
    await session.commit()

    hydrated = await _refetch_group(session, new_group.id)
    return serialize_counter_group(
        hydrated,
        user_id=current_user.id,
        context=guild_context,
    )


@router.patch("/{group_id}", response_model=CounterGroupRead)
async def update_counter_group(
    group_id: int,
    group_in: CounterGroupUpdate,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: CounterGroupsWrite,
) -> CounterGroupRead:
    group = await resource_access.load_authorized(
        session,
        Tool.counter_group,
        group_id,
        current_user,
        guild_context,
        access="write",
    )
    updated = False
    update_data = group_in.model_dump(exclude_unset=True)

    if "name" in update_data and update_data["name"] is not None:
        group.name = update_data["name"].strip()
        updated = True
    if "description" in update_data:
        group.description = update_data["description"]
        updated = True

    if updated:
        group.updated_at = datetime.now(timezone.utc)
        session.add(group)
        await session.commit()

    hydrated = await _refetch_group(session, group.id)
    result = serialize_counter_group(
        hydrated,
        user_id=guild_context.user_id,
        context=guild_context,
    )
    if updated:
        sockets.signal(
            routed_guild_id(session), Tool.counter_group, group_id, "group_updated"
        )
    return result


@router.delete("/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_counter_group(
    group_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> None:
    from app.services.tenant.soft_delete import trash

    group = await resource_access.load_authorized(
        session,
        Tool.counter_group,
        group_id,
        current_user,
        guild_context,
        action=Action.delete,
    )
    await trash(
        session,
        group,
        deleted_by_user_id=current_user.id,
    )
    await session.commit()
    sockets.signal(
        guild_context.guild_id, Tool.counter_group, group_id, "group_deleted"
    )


# ---------------------------------------------------------------------------
# Counters CRUD
# ---------------------------------------------------------------------------


@router.post(
    "/{group_id}/counters",
    response_model=CounterRead,
    status_code=status.HTTP_201_CREATED,
)
async def add_counter(
    group_id: int,
    counter_in: CounterCreate,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> CounterRead:
    group = await resource_access.load_authorized(
        session,
        Tool.counter_group,
        group_id,
        current_user,
        guild_context,
        access="write",
    )

    clamped = counters_service.clamp(counter_in.count, counter_in.min, counter_in.max)
    clamped_initial = counters_service.clamp(
        counter_in.initial_count, counter_in.min, counter_in.max
    )

    counter = Counter(
        counter_group_id=group.id,
        name=counter_in.name.strip(),
        color=counter_in.color,
        count=clamped,
        min=counter_in.min,
        max=counter_in.max,
        step=counter_in.step,
        initial_count=clamped_initial,
        view_mode=counter_in.view_mode,
        position=counter_in.position,
    )
    session.add(counter)
    await session.commit()

    hydrated = await counters_service.get_counter(
        session, counter.id, populate_existing=True
    )
    if not hydrated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=CounterMessages.NOT_FOUND
        )
    result = serialize_counter(hydrated, context=guild_context)
    sockets.signal(
        routed_guild_id(session), Tool.counter_group, group_id, "counter_added"
    )
    return result


@router.patch("/{group_id}/counters/{counter_id}", response_model=CounterRead)
async def update_counter(
    group_id: int,
    counter_id: int,
    counter_in: CounterUpdate,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> CounterRead:
    await resource_access.load_authorized(
        session,
        Tool.counter_group,
        group_id,
        current_user,
        guild_context,
        access="write",
    )
    counter = await _get_counter_for_group(session, group_id, counter_id)

    update_data = counter_in.model_dump(exclude_unset=True)

    # Drop explicit nulls for NOT NULL columns — a null is meaningless on PATCH
    # for these (only min/max are nullable). This keeps a `{"step": null}`
    # payload from reaching the constraint check (None <= 0 → TypeError → 500)
    # or a DB NOT NULL violation, treating it as "field not provided".
    for field in ("name", "step", "initial_count", "view_mode", "position"):
        if field in update_data and update_data[field] is None:
            del update_data[field]

    # Compute the prospective new state
    new_min: Optional[Decimal] = (
        update_data["min"] if "min" in update_data else counter.min
    )
    new_max: Optional[Decimal] = (
        update_data["max"] if "max" in update_data else counter.max
    )
    new_step: Decimal = update_data["step"] if "step" in update_data else counter.step
    new_view_mode: CounterViewMode = (
        update_data["view_mode"] if "view_mode" in update_data else counter.view_mode
    )

    try:
        _validate_counter_constraints(
            view_mode=new_view_mode,
            min_value=new_min,
            max_value=new_max,
            step=new_step,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        )

    updated = False
    for field in (
        "name",
        "color",
        "min",
        "max",
        "step",
        "initial_count",
        "view_mode",
        "position",
    ):
        if field in update_data:
            value = update_data[field]
            if field == "name" and value is not None:
                value = value.strip()
            setattr(counter, field, value)
            updated = True

    # Re-clamp count and initial_count to the new bounds
    counter.count = counters_service.clamp(counter.count, counter.min, counter.max)
    counter.initial_count = counters_service.clamp(
        counter.initial_count, counter.min, counter.max
    )

    if updated:
        counter.updated_at = datetime.now(timezone.utc)
        session.add(counter)
        await session.commit()

    hydrated = await counters_service.get_counter(
        session, counter.id, populate_existing=True
    )
    if not hydrated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=CounterMessages.NOT_FOUND
        )
    result = serialize_counter(hydrated, context=guild_context)
    sockets.signal(
        routed_guild_id(session), Tool.counter_group, group_id, "counter_updated"
    )
    return result


@router.delete(
    "/{group_id}/counters/{counter_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_counter(
    group_id: int,
    counter_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> None:
    from app.services.tenant.soft_delete import trash

    await resource_access.load_authorized(
        session,
        Tool.counter_group,
        group_id,
        current_user,
        guild_context,
        access="write",
    )
    counter = await _get_counter_for_group(session, group_id, counter_id)
    await trash(
        session,
        counter,
        deleted_by_user_id=current_user.id,
    )
    await session.commit()
    sockets.signal(
        routed_guild_id(session), Tool.counter_group, group_id, "counter_removed"
    )


# ---------------------------------------------------------------------------
# Counter value operations
# ---------------------------------------------------------------------------


async def _commit_and_broadcast_count(
    session: RLSSessionDep,
    group_id: int,
    counter: Counter,
    *,
    context: ActorContext,
) -> CounterRead:
    await session.commit()
    hydrated = await counters_service.get_counter(
        session, counter.id, populate_existing=True
    )
    if not hydrated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=CounterMessages.NOT_FOUND
        )
    result = serialize_counter(hydrated, context=context)
    sockets.signal(
        routed_guild_id(session), Tool.counter_group, group_id, "count_changed"
    )
    return result


@counters_router.get("/counters/{counter_id}", response_model=CounterRead)
async def read_counter(
    counter_id: int,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: CounterGroupsRead,
    include_deleted: IncludeDeletedDep = False,
) -> CounterRead:
    """One counter by id — the read-back for a ``counters.*`` event.

    Gated by read access on the group it belongs to, like reading the group.
    The counter's own id is the whole address, so there is no parent to
    mismatch — and no hand-written deleted check to contradict the request,
    which is what a read-back after a delete depends on.
    """
    counter = await counters_service.get_counter(session, counter_id)
    if not counter:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=CounterMessages.NOT_FOUND
        )
    await resource_access.load_authorized(
        session,
        Tool.counter_group,
        counter.counter_group_id,
        current_user,
        guild_context,
        access="read",
    )
    return serialize_counter(counter, context=guild_context)


@router.post("/{group_id}/counters/{counter_id}/set", response_model=CounterRead)
async def set_counter_count(
    group_id: int,
    counter_id: int,
    payload: CounterSetCountRequest,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: CounterGroupsWrite,
) -> CounterRead:
    await resource_access.load_authorized(
        session,
        Tool.counter_group,
        group_id,
        current_user,
        guild_context,
        access="write",
    )
    counter = await _get_counter_for_group(session, group_id, counter_id)
    await counters_service.set_count(session, counter, payload.count)
    return await _commit_and_broadcast_count(
        session, group_id, counter, context=guild_context
    )


@router.post("/{group_id}/counters/{counter_id}/increment", response_model=CounterRead)
async def increment_counter(
    group_id: int,
    counter_id: int,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: CounterGroupsWrite,
) -> CounterRead:
    await resource_access.load_authorized(
        session,
        Tool.counter_group,
        group_id,
        current_user,
        guild_context,
        access="write",
    )
    counter = await _get_counter_for_group(session, group_id, counter_id)
    await counters_service.increment_counter(session, counter)
    return await _commit_and_broadcast_count(
        session, group_id, counter, context=guild_context
    )


@router.post("/{group_id}/counters/{counter_id}/decrement", response_model=CounterRead)
async def decrement_counter(
    group_id: int,
    counter_id: int,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: CounterGroupsWrite,
) -> CounterRead:
    await resource_access.load_authorized(
        session,
        Tool.counter_group,
        group_id,
        current_user,
        guild_context,
        access="write",
    )
    counter = await _get_counter_for_group(session, group_id, counter_id)
    await counters_service.decrement_counter(session, counter)
    return await _commit_and_broadcast_count(
        session, group_id, counter, context=guild_context
    )


@router.post("/{group_id}/counters/{counter_id}/reset", response_model=CounterRead)
async def reset_counter(
    group_id: int,
    counter_id: int,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: CounterGroupsWrite,
) -> CounterRead:
    await resource_access.load_authorized(
        session,
        Tool.counter_group,
        group_id,
        current_user,
        guild_context,
        access="write",
    )
    counter = await _get_counter_for_group(session, group_id, counter_id)
    await counters_service.reset_counter(session, counter)
    return await _commit_and_broadcast_count(
        session, group_id, counter, context=guild_context
    )


@router.post("/{group_id}/reset-all", response_model=CounterGroupRead)
async def reset_all_counters(
    group_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> CounterGroupRead:
    group = await resource_access.load_authorized(
        session,
        Tool.counter_group,
        group_id,
        current_user,
        guild_context,
        access="write",
    )
    await counters_service.reset_all_counters(session, group)
    await session.commit()

    hydrated = await _refetch_group(session, group.id)
    result = serialize_counter_group(
        hydrated,
        user_id=current_user.id,
        context=guild_context,
    )
    sockets.signal(
        routed_guild_id(session), Tool.counter_group, group_id, "counters_reset"
    )
    return result


@router.post("/{group_id}/sort", response_model=CounterGroupRead)
async def sort_counters(
    group_id: int,
    payload: CounterSortRequest,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> CounterGroupRead:
    group = await resource_access.load_authorized(
        session,
        Tool.counter_group,
        group_id,
        current_user,
        guild_context,
        access="write",
    )
    await counters_service.sort_counters(
        session, group, field=payload.field, direction=payload.direction
    )
    await session.commit()

    hydrated = await _refetch_group(session, group.id)
    result = serialize_counter_group(
        hydrated,
        user_id=current_user.id,
        context=guild_context,
    )
    sockets.signal(
        routed_guild_id(session), Tool.counter_group, group_id, "counters_reordered"
    )
    return result


# ---------------------------------------------------------------------------
# Sharing (resource grants)
# ---------------------------------------------------------------------------


async def read_after_write(
    session: RLSSessionDep,
    group_id: int,
    user: Optional[User],
    guild_context: ActorContext,
) -> CounterGroupRead:
    """The counter group a write answers with: re-read after the commit,
    serialized.

    Registered in ``tool_lists.TOOL_LISTS`` so the shared sharing route
    (``tool_grants.py``) answers in this tool's own shape.
    """
    hydrated = await _refetch_group(session, group_id)
    return serialize_counter_group(
        hydrated, user_id=guild_context.user_id, context=guild_context
    )


# ---------------------------------------------------------------------------
# WebSocket
# ---------------------------------------------------------------------------


@router.websocket("/{group_id}/ws")
async def websocket_counter_group(
    websocket: WebSocket, guild_id: int, group_id: int
) -> None:
    """Change signals for one counter group: ``{type, id, timestamp}`` frames and a
    heartbeat. The client refetches on each; see ``serve_tool_stream``."""
    await serve_tool_stream(websocket, guild_id, Tool.counter_group, group_id)
