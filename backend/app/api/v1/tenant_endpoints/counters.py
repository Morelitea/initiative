"""Counter group endpoints — CRUD, value operations, permissions, WebSocket."""

from datetime import datetime, timezone
from decimal import Decimal
from typing import Annotated, List, Optional

import json
import logging

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from sqlalchemy import func
from sqlalchemy.orm import selectinload
from sqlmodel import select

from app.api.deps import (
    RLSSessionDep,
    establish_guild_access,
    get_current_active_user,
    get_guild_membership,
    GuildAccessError,
    GuildContext,
)
from app.core.config import settings
from app.core.messages import CounterMessages, InitiativeMessages
from app.db.session import AsyncSessionLocal
from app.models.tenant.counter import (
    Counter,
    CounterGroup,
    CounterViewMode,
)
from app.models.tenant.initiative import (
    Initiative,
    PermissionKey,
)
from app.models.tenant.resource_grant import ResourceAccessLevel, ResourceGrant
from app.models.platform.user import User
from app.schemas.tenant.resource_grant import ResourceGrantSchema
from app.schemas.tenant.counter import (
    CounterCreate,
    CounterGroupCreate,
    CounterGroupDuplicateRequest,
    CounterGroupListResponse,
    CounterGroupRead,
    CounterGroupUpdate,
    CounterRead,
    CounterSetCountRequest,
    CounterSortRequest,
    CounterUpdate,
    serialize_counter,
    serialize_counter_group,
    serialize_counter_group_summary,
    _validate_counter_constraints,
)
from app.services.tenant import counters as counters_service
from app.services import permissions as permissions_service
from app.services.tenant import recent_views as recent_views_service
from app.api import resource_access
from app.core.tools import Tool
from app.services import rls as rls_service
from app.services.stream_authz import authority as stream_authority
from app.services.platform.ws_auth import authenticate_ws_token
from app.schemas.tenant.recent_view import RecentViewWrite


router = APIRouter()
logger = logging.getLogger(__name__)

GuildContextDep = Annotated[GuildContext, Depends(get_guild_membership)]


async def _emit_counter(
    session,
    group_id: int,
    event_type: str,
    data: dict,
    *,
    guild_id: int | None = None,
) -> None:
    """Fan a counter event out through the streaming spine, guild-namespaced.

    Pass ``guild_id`` when the caller already holds it — required for the delete
    path, where the row is soft-deleted before this runs so a post-commit lookup
    would hit the global ``deleted_at IS NULL`` filter and find nothing, silently
    dropping the ``group_deleted`` event. Otherwise the group's guild is resolved
    from the (guild-routed) session (context replays automatically after a
    commit). One streaming spine; rooms are guild-namespaced (group ids are
    per-schema)."""
    if guild_id is None:
        guild_id = (
            await session.exec(
                select(CounterGroup.guild_id).where(CounterGroup.id == group_id)
            )
        ).one_or_none()
        if guild_id is None:
            return
    await stream_authority.emit(guild_id, "counter_group", group_id, event_type, data)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _get_initiative_for_counter_group(
    session: RLSSessionDep,
    initiative_id: int,
) -> Initiative:
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
            detail=CounterMessages.CREATE_PERMISSION_REQUIRED,
        )


async def _get_counter_group_with_access(
    session: RLSSessionDep,
    group_id: int,
    user: User,
    guild_context: GuildContext,
    *,
    access: str = "read",
    manage_access: bool = False,
) -> CounterGroup:
    """Fetch + authorize a counter group via the shared enforcement path."""
    return await resource_access.load_authorized(
        session,
        Tool.counter_group,
        group_id,
        user,
        guild_context,
        access=access,
        manage_access=manage_access,
    )


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


def _compute_my_permission(
    group: CounterGroup,
    user: User,
    guild_context: GuildContext,
) -> str | None:
    return resource_access.my_permission_level(
        group, Tool.counter_group, user, guild_context
    )


async def _refetch_group(session: RLSSessionDep, group_id: int) -> CounterGroup:
    group = await counters_service.get_counter_group(
        session, group_id, populate_existing=True
    )
    if not group:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=CounterMessages.GROUP_NOT_FOUND,
        )
    return group


# ---------------------------------------------------------------------------
# Counter Group CRUD
# ---------------------------------------------------------------------------


@router.get("/", response_model=CounterGroupListResponse)
async def list_counter_groups(
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
    initiative_id: Optional[int] = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> CounterGroupListResponse:
    conditions = [CounterGroup.guild_id == guild_context.guild_id]

    if initiative_id is not None:
        initiative = await session.get(Initiative, initiative_id)
        if initiative and not initiative.counters_enabled:
            return CounterGroupListResponse(
                items=[],
                total_count=0,
                page=page,
                page_size=page_size,
                has_next=False,
            )
        conditions.append(CounterGroup.initiative_id == initiative_id)
    else:
        conditions.append(
            CounterGroup.initiative_id.in_(
                select(Initiative.id).where(Initiative.counters_enabled == True)  # noqa: E712
            )
        )

    # A PAM grantee has no membership/permission rows; the grant already scopes
    # them to this guild at the RLS layer, so skip the app-layer narrowing
    # (whose permission-table joins would also fault on the unset guild var).
    if not rls_service.is_guild_admin(guild_context.role) and not guild_context.is_pam:
        visible_subq = counters_service.visible_counter_group_ids_subquery(
            current_user.id
        )
        conditions.append(CounterGroup.id.in_(visible_subq))

    count_subq = select(CounterGroup.id).where(*conditions).subquery()
    count_stmt = select(func.count()).select_from(count_subq)
    total_count = (await session.exec(count_stmt)).one()

    stmt = (
        select(CounterGroup)
        .where(*conditions)
        .options(
            selectinload(CounterGroup.counters),
            selectinload(CounterGroup.grants).selectinload(ResourceGrant.role),
            selectinload(CounterGroup.initiative).selectinload(Initiative.memberships),
        )
        .order_by(CounterGroup.updated_at.desc(), CounterGroup.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    result = await session.exec(stmt)
    groups = result.unique().all()

    items = [
        serialize_counter_group_summary(
            g,
            my_permission_level=_compute_my_permission(g, current_user, guild_context),
        )
        for g in groups
    ]

    has_next = page * page_size < total_count
    return CounterGroupListResponse(
        items=items,
        total_count=total_count,
        page=page,
        page_size=page_size,
        has_next=has_next,
    )


@router.get("/{group_id}", response_model=CounterGroupRead)
async def read_counter_group(
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
    group: Annotated[
        CounterGroup,
        Depends(resource_access.resource_dependency(Tool.counter_group, "read")),
    ],
) -> CounterGroupRead:
    """Access enforced by resource_dependency before the body runs."""
    return serialize_counter_group(
        group,
        my_permission_level=_compute_my_permission(group, current_user, guild_context),
    )


@router.post("/", response_model=CounterGroupRead, status_code=status.HTTP_201_CREATED)
async def create_counter_group(
    group_in: CounterGroupCreate,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> CounterGroupRead:
    initiative = await _get_initiative_for_counter_group(
        session, group_in.initiative_id
    )
    if not initiative.counters_enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=CounterMessages.FEATURE_DISABLED,
        )
    await _check_initiative_permission(
        session,
        initiative,
        current_user,
        guild_context,
        PermissionKey.create_counters,
    )

    group = CounterGroup(
        guild_id=guild_context.guild_id,
        initiative_id=initiative.id,
        created_by_id=current_user.id,
        name=group_in.name.strip(),
        description=group_in.description,
    )
    session.add(group)
    await session.flush()

    owner_perm = ResourceGrant(
        resource_type="counter_group",
        resource_id=group.id,
        user_id=current_user.id,
        role_id=None,
        level=ResourceAccessLevel.owner,
        guild_id=guild_context.guild_id,
        initiative_id=group.initiative_id,
    )
    session.add(owner_perm)

    # Apply the initial sharing exactly the way edits do — one grant list, one
    # code path (empty default = owner-only until shared).
    await permissions_service.replace_resource_grants(
        session,
        resource_type="counter_group",
        resource_id=group.id,
        guild_id=guild_context.guild_id,
        initiative_id=group.initiative_id,
        owner_id=current_user.id,
        grants=group_in.grants,
    )

    await session.commit()

    hydrated = await _refetch_group(session, group.id)
    return serialize_counter_group(
        hydrated,
        my_permission_level=_compute_my_permission(
            hydrated, current_user, guild_context
        ),
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
    source = await _get_counter_group_with_access(
        session, group_id, current_user, guild_context, access="read"
    )

    new_name = (
        payload.name.strip()
        if payload.name and payload.name.strip()
        else f"{source.name} (Copy)"
    )
    new_group = await counters_service.duplicate_counter_group(
        session,
        source,
        name=new_name,
        user_id=current_user.id,
        guild_id=guild_context.guild_id,
    )
    await session.commit()

    hydrated = await _refetch_group(session, new_group.id)
    return serialize_counter_group(
        hydrated,
        my_permission_level=_compute_my_permission(
            hydrated, current_user, guild_context
        ),
    )


@router.patch("/{group_id}", response_model=CounterGroupRead)
async def update_counter_group(
    group_id: int,
    group_in: CounterGroupUpdate,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> CounterGroupRead:
    group = await _get_counter_group_with_access(
        session, group_id, current_user, guild_context, access="write"
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
        my_permission_level=_compute_my_permission(
            hydrated, current_user, guild_context
        ),
    )
    if updated:
        await _emit_counter(
            session, group_id, "group_updated", result.model_dump(mode="json")
        )
    return result


@router.delete("/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_counter_group(
    group_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> None:
    from app.services.platform import guilds as guilds_service
    from app.services.tenant.soft_delete import soft_delete_entity

    group = await _get_counter_group_with_access(
        session, group_id, current_user, guild_context, access="read"
    )
    if not rls_service.is_guild_admin(guild_context.role):
        counters_service.require_counter_group_access(
            group, current_user, require_owner=True
        )
    retention_days = await guilds_service.get_guild_retention_days(
        session, guild_context.guild_id
    )
    await soft_delete_entity(
        session,
        group,
        deleted_by_user_id=current_user.id,
        retention_days=retention_days,
    )
    await session.commit()
    # Pass guild_id explicitly: the group is soft-deleted, so _emit_counter's
    # fallback lookup (deleted_at IS NULL filtered) would find nothing and drop
    # the event.
    await _emit_counter(
        session,
        group_id,
        "group_deleted",
        {"id": group_id},
        guild_id=guild_context.guild_id,
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
    group = await _get_counter_group_with_access(
        session, group_id, current_user, guild_context, access="write"
    )

    clamped = counters_service.clamp(counter_in.count, counter_in.min, counter_in.max)
    clamped_initial = counters_service.clamp(
        counter_in.initial_count, counter_in.min, counter_in.max
    )

    counter = Counter(
        guild_id=group.guild_id,
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
    result = serialize_counter(hydrated)
    await _emit_counter(
        session, group_id, "counter_added", result.model_dump(mode="json")
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
    await _get_counter_group_with_access(
        session, group_id, current_user, guild_context, access="write"
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
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
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
    result = serialize_counter(hydrated)
    await _emit_counter(
        session, group_id, "counter_updated", result.model_dump(mode="json")
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
    from app.services.platform import guilds as guilds_service
    from app.services.tenant.soft_delete import soft_delete_entity

    await _get_counter_group_with_access(
        session, group_id, current_user, guild_context, access="write"
    )
    counter = await _get_counter_for_group(session, group_id, counter_id)
    retention_days = await guilds_service.get_guild_retention_days(
        session, guild_context.guild_id
    )
    await soft_delete_entity(
        session,
        counter,
        deleted_by_user_id=current_user.id,
        retention_days=retention_days,
    )
    await session.commit()
    await _emit_counter(session, group_id, "counter_removed", {"id": counter_id})


# ---------------------------------------------------------------------------
# Counter value operations
# ---------------------------------------------------------------------------


async def _commit_and_broadcast_count(
    session: RLSSessionDep,
    group_id: int,
    counter: Counter,
) -> CounterRead:
    await session.commit()
    hydrated = await counters_service.get_counter(
        session, counter.id, populate_existing=True
    )
    if not hydrated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=CounterMessages.NOT_FOUND
        )
    result = serialize_counter(hydrated)
    await _emit_counter(
        session, group_id, "count_changed", result.model_dump(mode="json")
    )
    return result


@router.post("/{group_id}/counters/{counter_id}/set", response_model=CounterRead)
async def set_counter_count(
    group_id: int,
    counter_id: int,
    payload: CounterSetCountRequest,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> CounterRead:
    await _get_counter_group_with_access(
        session, group_id, current_user, guild_context, access="write"
    )
    counter = await _get_counter_for_group(session, group_id, counter_id)
    await counters_service.set_count(session, counter, payload.count)
    return await _commit_and_broadcast_count(session, group_id, counter)


@router.post("/{group_id}/counters/{counter_id}/increment", response_model=CounterRead)
async def increment_counter(
    group_id: int,
    counter_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> CounterRead:
    await _get_counter_group_with_access(
        session, group_id, current_user, guild_context, access="write"
    )
    counter = await _get_counter_for_group(session, group_id, counter_id)
    await counters_service.increment_counter(session, counter)
    return await _commit_and_broadcast_count(session, group_id, counter)


@router.post("/{group_id}/counters/{counter_id}/decrement", response_model=CounterRead)
async def decrement_counter(
    group_id: int,
    counter_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> CounterRead:
    await _get_counter_group_with_access(
        session, group_id, current_user, guild_context, access="write"
    )
    counter = await _get_counter_for_group(session, group_id, counter_id)
    await counters_service.decrement_counter(session, counter)
    return await _commit_and_broadcast_count(session, group_id, counter)


@router.post("/{group_id}/counters/{counter_id}/reset", response_model=CounterRead)
async def reset_counter(
    group_id: int,
    counter_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> CounterRead:
    await _get_counter_group_with_access(
        session, group_id, current_user, guild_context, access="write"
    )
    counter = await _get_counter_for_group(session, group_id, counter_id)
    await counters_service.reset_counter(session, counter)
    return await _commit_and_broadcast_count(session, group_id, counter)


@router.post("/{group_id}/reset-all", response_model=CounterGroupRead)
async def reset_all_counters(
    group_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> CounterGroupRead:
    group = await _get_counter_group_with_access(
        session, group_id, current_user, guild_context, access="write"
    )
    await counters_service.reset_all_counters(session, group)
    await session.commit()

    hydrated = await _refetch_group(session, group.id)
    result = serialize_counter_group(
        hydrated,
        my_permission_level=_compute_my_permission(
            hydrated, current_user, guild_context
        ),
    )
    await _emit_counter(
        session, group_id, "counters_reset", result.model_dump(mode="json")
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
    group = await _get_counter_group_with_access(
        session, group_id, current_user, guild_context, access="write"
    )
    await counters_service.sort_counters(
        session, group, field=payload.field, direction=payload.direction
    )
    await session.commit()

    hydrated = await _refetch_group(session, group.id)
    result = serialize_counter_group(
        hydrated,
        my_permission_level=_compute_my_permission(
            hydrated, current_user, guild_context
        ),
    )
    await _emit_counter(
        session, group_id, "counters_reordered", result.model_dump(mode="json")
    )
    return result


# ---------------------------------------------------------------------------
# Sharing (resource grants)
# ---------------------------------------------------------------------------


@router.put("/{group_id}/grants", response_model=CounterGroupRead)
async def set_counter_group_grants(
    group_id: int,
    grants: List[ResourceGrantSchema],
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> CounterGroupRead:
    """Replace the counter group's entire sharing state in one call — the body
    is the full list of grants (all-initiative-members / per-user / per-role).
    Every non-owner grant is rebuilt from it; the owner is always preserved.
    """
    # Write access is sufficient to manage sharing; only deleting the group is
    # reserved for owners. The owner row itself is preserved regardless.
    await resource_access.set_resource_grants(
        session, Tool.counter_group, group_id, current_user, guild_context, grants
    )

    hydrated = await _refetch_group(session, group_id)
    result = serialize_counter_group(
        hydrated,
        my_permission_level=_compute_my_permission(
            hydrated, current_user, guild_context
        ),
    )
    await _emit_counter(
        session,
        group_id,
        "permissions_changed",
        {"grants": [g.model_dump(mode="json") for g in result.grants]},
    )
    return result


# ---------------------------------------------------------------------------
# WebSocket
# ---------------------------------------------------------------------------


async def _ws_authenticate(token: str, session) -> Optional[User]:
    """Validate a session JWT or device token and return the user, or None.

    Delegates to the shared ``authenticate_ws_token`` helper so the
    ``token_version`` revocation check stays in lockstep with the HTTP auth
    path and the other realtime WebSocket endpoints (SEC-4).
    """
    return await authenticate_ws_token(token, session)


@router.websocket("/{group_id}/ws")
async def websocket_counter_group(
    websocket: WebSocket,
    guild_id: int,
    group_id: int,
) -> None:
    """Real-time updates for a counter group.

    Protocol: client sends `{"token": "..."}` first (the guild comes from the
    ``/g/{guild_id}`` path segment), server
    validates auth + DAC, then broadcasts `counter_added`, `counter_removed`,
    `counter_updated`, `count_changed`, `counters_reset`, `counters_reordered`,
    `group_updated`, `group_deleted`, `permissions_changed` events.
    """
    await websocket.accept()

    try:
        raw = await websocket.receive_text()
        auth_payload = json.loads(raw)
        token = auth_payload.get("token")
        if not token:
            token = websocket.cookies.get(settings.COOKIE_NAME)
        if not token:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return
    except (json.JSONDecodeError, ValueError, WebSocketDisconnect):
        try:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        except Exception:
            pass
        return

    async with AsyncSessionLocal() as session:
        user = await _ws_authenticate(token, session)
        if not user:
            logger.warning(f"Counter WS: auth failed for group {group_id}")
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
                f"Counter WS: user {user.id} has no access to guild {guild_id}"
            )
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

        group = await counters_service.get_counter_group(session, group_id)
        if not group or group.guild_id != guild_id:
            logger.warning(
                f"Counter WS: group {group_id} not found in guild {guild_id}"
            )
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

        # Mirror the feature gate enforced on every HTTP endpoint via
        # _get_counter_group_with_access — don't stream events for a group
        # whose initiative has counters disabled.
        if group.initiative and not group.initiative.counters_enabled:
            logger.warning(f"Counter WS: counters disabled for group {group_id}")
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

        # DAC level via the shared engine; the guild-admin / break-glass bypass is
        # applied inside compute_* through the active role context that
        # establish_guild_access set, so no separate admin check is needed.
        level = counters_service.compute_counter_group_permission(group, user.id)
        if level is None:
            logger.warning(
                f"Counter WS: user {user.id} has no access to group {group_id}"
            )
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

    logger.info(f"Counter WS: user {user.id} joined group {group_id}")

    # The streaming spine owns the socket lifecycle, fan-out, and continuous,
    # every-level re-authorization: a grant / membership / role / PAM change
    # disconnects this socket — immediately for guild/initiative-level removal
    # (revoke_user), within the bounded interval for within-initiative DAC. The
    # check re-runs the full join (establish_guild_access → load the group under
    # RLS → DAC).
    async def _authorize(check_session, check_user):
        grp = await counters_service.get_counter_group(check_session, group_id)
        if grp is None or grp.guild_id != guild_id:
            return False
        return (
            counters_service.compute_counter_group_permission(grp, check_user.id)
            is not None
        )

    await stream_authority.join(
        websocket,
        user,
        guild_id=guild_id,
        initiative_id=group.initiative_id,
        resource_type="counter_group",
        resource_id=group_id,
        authorize=_authorize,
    )

    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await stream_authority.leave(websocket)
        logger.info(f"Counter WS: user {user.id} left group {group_id}")


# ---------------------------------------------------------------------------
# Recent-view tracking (powers the layout header tabs bar)
# ---------------------------------------------------------------------------


@router.post("/{group_id}/view", response_model=RecentViewWrite)
async def record_counter_group_view(
    group_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> RecentViewWrite:
    group = await _get_counter_group_with_access(
        session, group_id, current_user, guild_context, access="read"
    )
    record = await recent_views_service.record_view(
        session,
        user_id=current_user.id,
        entity_type="counter_group",
        entity_id=group.id,
        persist=not guild_context.is_pam,
        limit=current_user.recent_tabs_limit,
    )
    return RecentViewWrite(
        entity_type="counter_group",
        entity_id=group.id,
        last_viewed_at=record.last_viewed_at,
    )


@router.delete("/{group_id}/view", status_code=status.HTTP_204_NO_CONTENT)
async def clear_counter_group_view(
    group_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> None:
    group = await _get_counter_group_with_access(
        session, group_id, current_user, guild_context, access="read"
    )
    await recent_views_service.clear_view(
        session,
        user_id=current_user.id,
        entity_type="counter_group",
        entity_id=group.id,
    )
