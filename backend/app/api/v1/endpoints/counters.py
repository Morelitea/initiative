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
from app.core.messages import CounterMessages, InitiativeMessages
from app.db.session import AsyncSessionLocal, reapply_rls_context, set_rls_context
from app.models.counter import (
    Counter,
    CounterGroup,
    CounterGroupPermission,
    CounterGroupRolePermission,
    CounterPermissionLevel,
    CounterViewMode,
)
from app.models.guild import GuildMembership
from app.models.initiative import (
    Initiative,
    InitiativeMember,
    InitiativeRoleModel,
    PermissionKey,
)
from app.models.user import User, UserStatus
from app.schemas.counter import (
    CounterCreate,
    CounterGroupCreate,
    CounterGroupDuplicateRequest,
    CounterGroupListResponse,
    CounterGroupPermissionCreate,
    CounterGroupPermissionRead,
    CounterGroupRead,
    CounterGroupRolePermissionCreate,
    CounterGroupRolePermissionRead,
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
from app.schemas.token import TokenPayload
from app.services import counters as counters_service
from app.services import recent_views as recent_views_service
from app.services import rls as rls_service
from app.services import user_tokens
from app.services.counter_realtime import counter_manager
from app.schemas.recent_view import RecentViewWrite

import jwt

router = APIRouter()
logger = logging.getLogger(__name__)

GuildContextDep = Annotated[GuildContext, Depends(get_guild_membership)]


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
    group = await counters_service.get_counter_group(session, group_id)
    if not group:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=CounterMessages.GROUP_NOT_FOUND,
        )
    if group.initiative and not group.initiative.counters_enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=CounterMessages.FEATURE_DISABLED,
        )
    # A PAM grant gives content read/write only — never access-control
    # management. Those writes target counter_group_permissions which RLS won't
    # let a grant write, so reject grantees with a clean 403 (not a 500).
    if manage_access and guild_context.is_pam:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=CounterMessages.GRANT_CANNOT_MANAGE,
        )
    if not rls_service.is_guild_admin(guild_context.role):
        counters_service.require_counter_group_access(group, user, access=access)
    return group


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
    if rls_service.is_guild_admin(guild_context.role):
        return CounterPermissionLevel.owner.value
    return counters_service.compute_counter_group_permission(group, user.id)


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
            selectinload(CounterGroup.permissions),
            selectinload(CounterGroup.role_permissions),
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
    group_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> CounterGroupRead:
    group = await _get_counter_group_with_access(
        session, group_id, current_user, guild_context, access="read"
    )
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

    owner_perm = CounterGroupPermission(
        counter_group_id=group.id,
        user_id=current_user.id,
        guild_id=guild_context.guild_id,
        level=CounterPermissionLevel.owner,
    )
    session.add(owner_perm)

    if group_in.role_permissions:
        role_ids = {
            rp.initiative_role_id
            for rp in group_in.role_permissions
            if rp.level != CounterPermissionLevel.owner
        }
        valid_role_ids: set[int] = set()
        if role_ids:
            result = await session.exec(
                select(InitiativeRoleModel.id).where(
                    InitiativeRoleModel.id.in_(role_ids),
                    InitiativeRoleModel.initiative_id == initiative.id,
                )
            )
            valid_role_ids = set(result.all())
        for rp in group_in.role_permissions:
            if (
                rp.initiative_role_id not in valid_role_ids
                or rp.level == CounterPermissionLevel.owner
            ):
                continue
            session.add(
                CounterGroupRolePermission(
                    counter_group_id=group.id,
                    initiative_role_id=rp.initiative_role_id,
                    guild_id=guild_context.guild_id,
                    level=rp.level,
                )
            )

    if group_in.user_permissions:
        requested = {
            up.user_id
            for up in group_in.user_permissions
            if up.user_id != current_user.id
        }
        valid_ids: set[int] = set()
        if requested:
            result = await session.exec(
                select(InitiativeMember.user_id).where(
                    InitiativeMember.initiative_id == initiative.id,
                    InitiativeMember.user_id.in_(requested),
                )
            )
            valid_ids = set(result.all())
        for up in group_in.user_permissions:
            if up.user_id in valid_ids and up.level != CounterPermissionLevel.owner:
                session.add(
                    CounterGroupPermission(
                        counter_group_id=group.id,
                        user_id=up.user_id,
                        guild_id=guild_context.guild_id,
                        level=up.level,
                    )
                )

    await session.commit()
    await reapply_rls_context(session)

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
    await reapply_rls_context(session)

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
        await reapply_rls_context(session)

    hydrated = await _refetch_group(session, group.id)
    result = serialize_counter_group(
        hydrated,
        my_permission_level=_compute_my_permission(
            hydrated, current_user, guild_context
        ),
    )
    if updated:
        await counter_manager.broadcast(
            group_id, "group_updated", result.model_dump(mode="json")
        )
    return result


@router.delete("/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_counter_group(
    group_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> None:
    from app.services import guilds as guilds_service
    from app.services.soft_delete import soft_delete_entity

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
    await counter_manager.broadcast(group_id, "group_deleted", {"id": group_id})


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
    await reapply_rls_context(session)

    hydrated = await counters_service.get_counter(
        session, counter.id, populate_existing=True
    )
    if not hydrated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=CounterMessages.NOT_FOUND
        )
    result = serialize_counter(hydrated)
    await counter_manager.broadcast(
        group_id, "counter_added", result.model_dump(mode="json")
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
        await reapply_rls_context(session)

    hydrated = await counters_service.get_counter(
        session, counter.id, populate_existing=True
    )
    if not hydrated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=CounterMessages.NOT_FOUND
        )
    result = serialize_counter(hydrated)
    await counter_manager.broadcast(
        group_id, "counter_updated", result.model_dump(mode="json")
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
    from app.services import guilds as guilds_service
    from app.services.soft_delete import soft_delete_entity

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
    await counter_manager.broadcast(group_id, "counter_removed", {"id": counter_id})


# ---------------------------------------------------------------------------
# Counter value operations
# ---------------------------------------------------------------------------


async def _commit_and_broadcast_count(
    session: RLSSessionDep,
    group_id: int,
    counter: Counter,
) -> CounterRead:
    await session.commit()
    await reapply_rls_context(session)
    hydrated = await counters_service.get_counter(
        session, counter.id, populate_existing=True
    )
    if not hydrated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=CounterMessages.NOT_FOUND
        )
    result = serialize_counter(hydrated)
    await counter_manager.broadcast(
        group_id, "count_changed", result.model_dump(mode="json")
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
    await reapply_rls_context(session)

    hydrated = await _refetch_group(session, group.id)
    result = serialize_counter_group(
        hydrated,
        my_permission_level=_compute_my_permission(
            hydrated, current_user, guild_context
        ),
    )
    await counter_manager.broadcast(
        group_id, "counters_reset", result.model_dump(mode="json")
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
    await reapply_rls_context(session)

    hydrated = await _refetch_group(session, group.id)
    result = serialize_counter_group(
        hydrated,
        my_permission_level=_compute_my_permission(
            hydrated, current_user, guild_context
        ),
    )
    await counter_manager.broadcast(
        group_id, "counters_reordered", result.model_dump(mode="json")
    )
    return result


# ---------------------------------------------------------------------------
# Permissions (DAC)
# ---------------------------------------------------------------------------


@router.get("/{group_id}/permissions")
async def list_counter_group_permissions(
    group_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> dict:
    group = await _get_counter_group_with_access(
        session, group_id, current_user, guild_context, access="read"
    )

    permissions = [
        CounterGroupPermissionRead(
            user_id=p.user_id,
            level=p.level,
            created_at=p.created_at,
        )
        for p in (group.permissions or [])
    ]

    role_permissions = []
    for rp in group.role_permissions or []:
        role = getattr(rp, "role", None)
        role_permissions.append(
            CounterGroupRolePermissionRead(
                initiative_role_id=rp.initiative_role_id,
                role_name=getattr(role, "name", "") if role else "",
                role_display_name=getattr(role, "display_name", "") if role else "",
                level=rp.level,
                created_at=rp.created_at,
            )
        )

    return {
        "permissions": permissions,
        "role_permissions": role_permissions,
    }


@router.put("/{group_id}/permissions", response_model=List[CounterGroupPermissionRead])
async def set_counter_group_permissions(
    group_id: int,
    permissions_in: List[CounterGroupPermissionCreate],
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> List[CounterGroupPermissionRead]:
    # Write access is sufficient to manage permissions; only deleting the group
    # is reserved for owners. The owner row itself is preserved below regardless.
    group = await _get_counter_group_with_access(
        session,
        group_id,
        current_user,
        guild_context,
        access="write",
        manage_access=True,
    )

    owner_user_id: int | None = None
    for p in group.permissions or []:
        if p.level == CounterPermissionLevel.owner:
            owner_user_id = p.user_id
            break

    if owner_user_id is not None:
        delete_stmt = sa_delete(CounterGroupPermission).where(
            CounterGroupPermission.counter_group_id == group.id,
            CounterGroupPermission.user_id != owner_user_id,
        )
    else:
        delete_stmt = sa_delete(CounterGroupPermission).where(
            CounterGroupPermission.counter_group_id == group.id,
            CounterGroupPermission.level != CounterPermissionLevel.owner,
        )
    await session.exec(delete_stmt)

    for perm_in in permissions_in:
        if perm_in.user_id == owner_user_id:
            continue
        if perm_in.level == CounterPermissionLevel.owner:
            continue
        session.add(
            CounterGroupPermission(
                counter_group_id=group.id,
                user_id=perm_in.user_id,
                guild_id=group.guild_id,
                level=perm_in.level,
            )
        )

    await session.commit()
    await reapply_rls_context(session)

    hydrated = await _refetch_group(session, group.id)
    perms_result = [
        CounterGroupPermissionRead(
            user_id=p.user_id,
            level=p.level,
            created_at=p.created_at,
        )
        for p in (hydrated.permissions or [])
    ]
    await counter_manager.broadcast(
        group_id,
        "permissions_changed",
        {"permissions": [p.model_dump(mode="json") for p in perms_result]},
    )
    return perms_result


@router.put(
    "/{group_id}/role-permissions", response_model=List[CounterGroupRolePermissionRead]
)
async def set_counter_group_role_permissions(
    group_id: int,
    role_permissions_in: List[CounterGroupRolePermissionCreate],
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> List[CounterGroupRolePermissionRead]:
    # Write access is sufficient to manage role permissions (delete is owner-only).
    group = await _get_counter_group_with_access(
        session,
        group_id,
        current_user,
        guild_context,
        access="write",
        manage_access=True,
    )

    delete_stmt = sa_delete(CounterGroupRolePermission).where(
        CounterGroupRolePermission.counter_group_id == group.id,
    )
    await session.exec(delete_stmt)

    for rp_in in role_permissions_in:
        if rp_in.level == CounterPermissionLevel.owner:
            continue
        session.add(
            CounterGroupRolePermission(
                counter_group_id=group.id,
                initiative_role_id=rp_in.initiative_role_id,
                guild_id=group.guild_id,
                level=rp_in.level,
            )
        )

    await session.commit()
    await reapply_rls_context(session)

    hydrated = await _refetch_group(session, group.id)
    role_perms_result: List[CounterGroupRolePermissionRead] = []
    for rp in hydrated.role_permissions or []:
        role = getattr(rp, "role", None)
        role_perms_result.append(
            CounterGroupRolePermissionRead(
                initiative_role_id=rp.initiative_role_id,
                role_name=getattr(role, "name", "") if role else "",
                role_display_name=getattr(role, "display_name", "") if role else "",
                level=rp.level,
                created_at=rp.created_at,
            )
        )
    await counter_manager.broadcast(
        group_id,
        "permissions_changed",
        {"role_permissions": [rp.model_dump(mode="json") for rp in role_perms_result]},
    )
    return role_perms_result


# ---------------------------------------------------------------------------
# WebSocket
# ---------------------------------------------------------------------------


async def _ws_authenticate(token: str, session) -> Optional[User]:
    try:
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
        )
        token_data = TokenPayload(**payload)
        if token_data.sub:
            stmt = select(User).where(User.id == int(token_data.sub))
            result = await session.exec(stmt)
            user = result.one_or_none()
            if user and user.status == UserStatus.active:
                return user
    except jwt.PyJWTError:
        pass

    device_token = await user_tokens.get_device_token(session, token=token)
    if device_token:
        stmt = select(User).where(User.id == device_token.user_id)
        result = await session.exec(stmt)
        user = result.one_or_none()
        if user and user.status == UserStatus.active:
            return user
    return None


@router.websocket("/{group_id}/ws")
async def websocket_counter_group(
    websocket: WebSocket,
    group_id: int,
) -> None:
    """Real-time updates for a counter group.

    Protocol: client sends `{"token": "...", "guild_id": <int>}` first, server
    validates auth + DAC, then broadcasts `counter_added`, `counter_removed`,
    `counter_updated`, `count_changed`, `counters_reset`, `counters_reordered`,
    `group_updated`, `group_deleted`, `permissions_changed` events.
    """
    await websocket.accept()

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

    async with AsyncSessionLocal() as session:
        user = await _ws_authenticate(token, session)
        if not user:
            logger.warning(f"Counter WS: auth failed for group {group_id}")
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

        await set_rls_context(session, user_id=user.id, guild_id=guild_id)

        stmt = select(GuildMembership).where(
            GuildMembership.guild_id == guild_id,
            GuildMembership.user_id == user.id,
        )
        result = await session.exec(stmt)
        membership = result.one_or_none()
        if not membership:
            logger.warning(f"Counter WS: user {user.id} not in guild {guild_id}")
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

        is_admin = rls_service.is_guild_admin(membership.role)
        if not is_admin:
            level = counters_service.compute_counter_group_permission(group, user.id)
            if level is None:
                logger.warning(
                    f"Counter WS: user {user.id} has no access to group {group_id}"
                )
                await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
                return

    await counter_manager.connect(group_id, websocket)
    logger.info(f"Counter WS: user {user.id} joined group {group_id}")

    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await counter_manager.disconnect(group_id, websocket)
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
