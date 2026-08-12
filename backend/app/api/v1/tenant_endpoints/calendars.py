"""Calendar endpoints — the shareable container for events.

A calendar is to events what a project is to tasks: creation is gated at the
initiative level (calendars_enabled + create_calendars), and everything inside
the calendar flows from its resource-grant DAC (``resource_grants`` +
``PUT /{id}/grants``). Events themselves carry no grants.
"""

from datetime import datetime, timezone
from typing import Annotated, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlmodel import select

from app.api import resource_access
from app.api.deps import (
    GuildContext,
    RLSSessionDep,
    get_current_active_user,
    get_guild_membership,
)
from app.core import role_context
from app.core.messages import CalendarMessages, InitiativeMessages
from app.db.session import get_admin_session
from app.models.platform.guild import GuildRole
from app.services.cross_guild import gather_across_guilds, member_guild_ids
from app.core.tools import Tool
from app.models.tenant.calendar import Calendar
from app.models.tenant.initiative import Initiative, PermissionKey
from app.models.platform.user import User
from app.models.tenant.resource_grant import ResourceAccessLevel, ResourceGrant
from app.schemas.tenant.calendar import (
    CalendarCreate,
    CalendarListResponse,
    CalendarRead,
    CalendarUpdate,
    serialize_calendar,
    serialize_calendar_summary,
)
from app.schemas.tenant.recent_view import RecentViewWrite
from app.schemas.tenant.resource_grant import ResourceGrantSchema
from app.services import permissions as permissions_service
from app.services import rls as rls_service
from app.services.tenant import calendars as calendars_service
from app.services.tenant import recent_views as recent_views_service
from app.services.tenant import tags as tags_service

router = APIRouter()

# Cross-guild personal aggregate ("My Calendar" grouping panel), mounted under
# /api/v1/me; routes per member guild via gather_across_guilds.
me_router = APIRouter()

GuildContextDep = Annotated[GuildContext, Depends(get_guild_membership)]
AdminSessionDep = Annotated[AsyncSession, Depends(get_admin_session)]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _get_initiative_for_calendar(
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


async def _check_create_permission(
    session: RLSSessionDep,
    initiative: Initiative,
    user: User,
    guild_context: GuildContext,
) -> None:
    if rls_service.is_guild_admin(guild_context.role):
        return
    has_perm = await rls_service.check_initiative_permission(
        session,
        initiative_id=initiative.id,
        user=user,
        permission_key=PermissionKey.create_calendars,
    )
    if not has_perm:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=CalendarMessages.CREATE_PERMISSION_REQUIRED,
        )


async def _refetch_calendar(session: RLSSessionDep, calendar_id: int) -> Calendar:
    calendar = await calendars_service.get_calendar(
        session, calendar_id, populate_existing=True
    )
    if not calendar:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=CalendarMessages.NOT_FOUND,
        )
    return calendar


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


@router.get("/", response_model=CalendarListResponse)
async def list_calendars(
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
    initiative_id: Optional[int] = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=200),
) -> CalendarListResponse:
    """List calendars visible to the current user (guild admins see all)."""
    conditions = [Calendar.guild_id == guild_context.guild_id]

    if initiative_id is not None:
        initiative = await session.get(Initiative, initiative_id)
        if initiative and not initiative.calendars_enabled:
            return CalendarListResponse(
                items=[],
                total_count=0,
                page=page,
                page_size=page_size,
                has_next=False,
            )
        conditions.append(Calendar.initiative_id == initiative_id)
    else:
        conditions.append(calendars_service.tool_enabled_clause())

    # DAC: non-admins (and non-PAM) see only calendars shared with them.
    if not rls_service.is_guild_admin(guild_context.role) and not guild_context.is_pam:
        conditions.append(
            Calendar.id.in_(
                permissions_service.visible_resource_ids_subquery(
                    "calendar", current_user.id
                )
            )
        )

    count_subq = select(Calendar.id).where(*conditions).subquery()
    total_count = (
        await session.exec(select(func.count()).select_from(count_subq))
    ).one()

    stmt = (
        select(Calendar)
        .where(*conditions)
        .options(*calendars_service.calendar_loader_options())
        .order_by(Calendar.name.asc(), Calendar.id.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    result = await session.exec(stmt)
    calendars = result.unique().all()

    items = [serialize_calendar_summary(c, user_id=current_user.id) for c in calendars]
    has_next = page * page_size < total_count
    return CalendarListResponse(
        items=items,
        total_count=total_count,
        page=page,
        page_size=page_size,
        has_next=has_next,
    )


@router.get("/{calendar_id}", response_model=CalendarRead)
async def read_calendar(
    calendar_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> CalendarRead:
    calendar = await resource_access.load_authorized(
        session, Tool.calendar, calendar_id, current_user, guild_context
    )
    return serialize_calendar(calendar, user_id=current_user.id)


@router.post("/", response_model=CalendarRead, status_code=status.HTTP_201_CREATED)
async def create_calendar(
    calendar_in: CalendarCreate,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> CalendarRead:
    """Create a calendar. Requires create_calendars permission on the
    initiative (or guild admin); the creator gets the owner grant."""
    initiative = await _get_initiative_for_calendar(session, calendar_in.initiative_id)
    if not initiative.calendars_enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=CalendarMessages.FEATURE_DISABLED,
        )
    await _check_create_permission(session, initiative, current_user, guild_context)

    calendar = Calendar(
        guild_id=guild_context.guild_id,
        initiative_id=initiative.id,
        created_by_id=current_user.id,
        name=calendar_in.name.strip(),
        description=calendar_in.description,
        color=calendar_in.color,
    )
    session.add(calendar)
    await session.flush()

    session.add(
        ResourceGrant(
            resource_type="calendar",
            resource_id=calendar.id,
            user_id=current_user.id,
            role_id=None,
            level=ResourceAccessLevel.owner,
            guild_id=guild_context.guild_id,
            initiative_id=initiative.id,
        )
    )

    # Apply the initial sharing exactly the way edits do — one grant list, one
    # code path (defaults to Viewer for all initiative members).
    await permissions_service.replace_resource_grants(
        session,
        resource_type="calendar",
        resource_id=calendar.id,
        guild_id=guild_context.guild_id,
        initiative_id=initiative.id,
        owner_id=current_user.id,
        grants=calendar_in.grants,
    )

    if calendar_in.tag_ids:
        await tags_service.set_entity_tags(
            session,
            tags_service.TOOL_TAG_LINKS[Tool.calendar],
            guild_id=guild_context.guild_id,
            entity_id=calendar.id,
            tag_ids=calendar_in.tag_ids,
        )

    await session.commit()
    hydrated = await _refetch_calendar(session, calendar.id)
    return serialize_calendar(hydrated, user_id=current_user.id)


@router.patch("/{calendar_id}", response_model=CalendarRead)
async def update_calendar(
    calendar_id: int,
    calendar_in: CalendarUpdate,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> CalendarRead:
    """Rename/update a calendar. Requires write access."""
    calendar = await resource_access.load_authorized(
        session,
        Tool.calendar,
        calendar_id,
        current_user,
        guild_context,
        access="write",
    )
    updated = False
    update_data = calendar_in.model_dump(exclude_unset=True)

    if "name" in update_data and update_data["name"] is not None:
        calendar.name = update_data["name"].strip()
        updated = True
    if "description" in update_data:
        calendar.description = update_data["description"]
        updated = True
    if "color" in update_data and update_data["color"] is not None:
        calendar.color = update_data["color"]
        updated = True

    if updated:
        calendar.updated_at = datetime.now(timezone.utc)
        session.add(calendar)
        await session.commit()

    hydrated = await _refetch_calendar(session, calendar.id)
    return serialize_calendar(hydrated, user_id=current_user.id)


@router.delete("/{calendar_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_calendar(
    calendar_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> None:
    """Soft-delete a calendar (cascades to its events). Requires owner
    permission or guild admin."""
    from app.services.platform import guilds as guilds_service
    from app.services.tenant.soft_delete import soft_delete_entity

    calendar = await resource_access.load_authorized(
        session,
        Tool.calendar,
        calendar_id,
        current_user,
        guild_context,
        require_owner=not rls_service.is_guild_admin(guild_context.role),
    )
    retention_days = await guilds_service.get_guild_retention_days(
        session, guild_context.guild_id
    )
    await soft_delete_entity(
        session,
        calendar,
        deleted_by_user_id=current_user.id,
        retention_days=retention_days,
    )
    await session.commit()


# ---------------------------------------------------------------------------
# Cross-guild personal view
# ---------------------------------------------------------------------------


@me_router.get("/calendars", response_model=CalendarListResponse)
async def list_my_calendars(
    session: AdminSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_ids: Optional[List[int]] = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=200, ge=1, le=200),
) -> CalendarListResponse:
    """List the calendars visible to the user across all their guilds — the
    backing data for the My Calendar grouping panel.

    Mirrors ``list_my_calendar_events``: visit each member guild schema under
    the user's own RLS context (guild isolation + DAC hold), merge, and
    paginate in Python (per-schema SQL can't limit across schemas).
    """

    def _fetch(guild_session, guild_id):  # type: ignore[no-untyped-def]
        # A guild calendar is one of the user's own calendars like any other, so
        # it belongs in this view — it is reached here and from the app, and
        # nowhere that belongs to an initiative.
        conditions = [calendars_service.tool_enabled_clause()]
        if role_context.active_guild_role(guild_id) != GuildRole.admin.value:
            conditions.append(
                Calendar.id.in_(
                    permissions_service.visible_resource_ids_subquery(
                        "calendar", current_user.id
                    )
                )
            )
        stmt = (
            select(Calendar)
            .where(*conditions)
            .options(*calendars_service.calendar_loader_options())
        )
        return _exec_calendars(guild_session, stmt)

    target_guilds = await member_guild_ids(
        session, current_user.id, restrict_to=guild_ids
    )
    calendars = await gather_across_guilds(
        session, current_user.id, target_guilds, _fetch
    )
    # Merge-sort across guilds (per-schema SQL can't order across schemas).
    calendars.sort(key=lambda c: (c.name.lower(), c.guild_id, c.id))

    total_count = len(calendars)
    start = (page - 1) * page_size
    page_calendars = calendars[start : start + page_size]
    items = [
        serialize_calendar_summary(c, user_id=current_user.id) for c in page_calendars
    ]
    return CalendarListResponse(
        items=items,
        total_count=total_count,
        page=page,
        page_size=page_size,
        has_next=page * page_size < total_count,
    )


async def _exec_calendars(session, stmt) -> list[Calendar]:
    """Run a Calendar select and return de-duplicated rows as a list."""
    result = await session.exec(stmt)
    return list(result.unique().all())


# ---------------------------------------------------------------------------
# Sharing (resource grants)
# ---------------------------------------------------------------------------


@router.put("/{calendar_id}/grants", response_model=CalendarRead)
async def set_calendar_grants(
    calendar_id: int,
    grants: List[ResourceGrantSchema],
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> CalendarRead:
    """Replace the calendar's entire sharing state in one call — the body is
    the full list of grants (all-initiative-members / per-user / per-role).
    Every non-owner grant is rebuilt from it; the owner is always preserved.
    """
    await resource_access.set_resource_grants(
        session, Tool.calendar, calendar_id, current_user, guild_context, grants
    )
    hydrated = await _refetch_calendar(session, calendar_id)
    return serialize_calendar(hydrated, user_id=current_user.id)


# ---------------------------------------------------------------------------
# Recent-view tracking (powers the layout header tabs bar)
# ---------------------------------------------------------------------------


@router.post("/{calendar_id}/view", response_model=RecentViewWrite)
async def record_calendar_view(
    calendar_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> RecentViewWrite:
    calendar = await resource_access.load_authorized(
        session, Tool.calendar, calendar_id, current_user, guild_context
    )
    record = await recent_views_service.record_view(
        session,
        user_id=current_user.id,
        entity_type="calendar",
        entity_id=calendar.id,
        persist=not guild_context.is_pam,
        limit=current_user.recent_tabs_limit,
    )
    return RecentViewWrite(
        entity_type="calendar",
        entity_id=calendar.id,
        last_viewed_at=record.last_viewed_at,
    )


@router.delete("/{calendar_id}/view", status_code=status.HTTP_204_NO_CONTENT)
async def clear_calendar_view(
    calendar_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> None:
    await resource_access.load_authorized(
        session, Tool.calendar, calendar_id, current_user, guild_context
    )
    await recent_views_service.clear_view(
        session,
        user_id=current_user.id,
        entity_type="calendar",
        entity_id=calendar_id,
    )
